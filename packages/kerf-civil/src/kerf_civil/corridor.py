"""
Corridor model — sweep a parametric road cross-section template (point-coded
assembly) along a horizontal + vertical alignment to produce:

  • Per-station cross-section point sets (CL, edge-lane, shoulder, ditch,
    daylight) with full cut/fill side-slope intersection against a TIN terrain.
  • 3-D corridor surface (feature-lines / strings) for every coded string.
  • Per-station earthwork cut/fill areas using the shoelace formula on the
    design+terrain polygon.
  • Mass-haul diagram (Brückner curve) via average-end-area integration.

Standard methods
----------------
  AASHTO Green Book (GDPS-4-M) cross-section design — §2.2 lane widths,
  §2.3 shoulders, §4.2 normal crown, §3.3.2 cut/fill side slopes.
  Daylight-slope intersection: iterative offset stepping to find where the
  design side-slope meets the TIN surface elevation.
  Average-end-area volume: AASHTO GDPS-4-M §2.2.3.

Terminology (AASHTO)
--------------------
  CL       — centreline
  EL / ER  — edge of travel lane (left/right)
  SL / SR  — shoulder edge (left/right)
  DL / DR  — ditch/hinge point (top of cut or toe of fill)
  DTL/DTR  — daylight point (slope intercepts existing ground)

A TypicalSection defines widths and slopes; the Corridor sweeps it at
requested stations.  Terrain is optional — when supplied, daylight points are
computed by intersecting the design side-slope against the TIN.  When absent,
a flat ground plane at the existing shoulder elevation is assumed (conservative
pass-through for cross-section geometry only).

This module is deliberately pure-Python (no NumPy hard dependency in the
public API) so it can be imported in any environment.  The terrain-aware
daylight computation uses ``kerf_civil.tin.interpolate_z`` when a TIN is
passed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from kerf_civil.tin import TIN  # noqa: F401


# ---------------------------------------------------------------------------
# Typical section definition (point-coded assembly)
# ---------------------------------------------------------------------------

@dataclass
class TypicalSection:
    """Parametric symmetric two-lane typical section — point-coded assembly.

    The assembly follows AASHTO Green Book §2.2–§2.3 (lane widths, shoulders)
    and §3.3.2 (side-slope selection for cut/fill).

    Point codes (left side, mirrored for right):
      CL         centreline
      EL / ER    edge of travel lane
      SL / SR    edge of shoulder (hinge point for cut; toe for fill)
      DL / DR    ditch bottom / fill toe (only for cut sections with ditch)
      DTL / DTR  daylight point (slope intercepts terrain)

    Parameters
    ----------
    lane_width:
        Width of a single travel lane (metres). AASHTO §2.2 standard: 3.6–3.7 m.
    shoulder_width:
        Width of the shoulder (metres). AASHTO §2.3: 0.6–3.6 m.
    cut_slope:
        Cut backslope H:V ratio.  E.g. 2.0 → 2H:1V.  AASHTO §3.3.2 typical:
        1:1 (rock) to 3:1 (unstable soils).
    fill_slope:
        Fill foreslope H:V ratio.  AASHTO §3.3.2 typical: 2:1 to 4:1.
    lanes_each_side:
        Number of lanes each side of the centreline.
    crown_slope_pct:
        Normal crown (cross-fall), percent.  AASHTO §4.2: typically 1.5–2.0 %.
        Positive = pavement falls away from CL.
    shoulder_slope_pct:
        Shoulder cross-slope, percent (AASHTO §2.3: typically 5–8 %).
        Falls away from the edge-of-lane in the same direction as the crown.
    ditch_width:
        Width of roadside ditch at the bottom of the cut slope (metres).
        Set to 0.0 to omit a ditch (shoulder hinge goes directly to side-slope).
        AASHTO §3.3.3: typical 0.6–1.2 m bottom width.
    ditch_depth:
        Depth of the ditch below the shoulder hinge point (metres).
        Relevant only when ditch_width > 0.
    """

    lane_width: float = 3.65
    shoulder_width: float = 2.4
    cut_slope: float = 2.0
    fill_slope: float = 2.0
    lanes_each_side: int = 1
    crown_slope_pct: float = 2.0
    shoulder_slope_pct: float = 5.0
    ditch_width: float = 0.0
    ditch_depth: float = 0.0

    def pavement_half_width(self) -> float:
        """Horizontal distance from centreline to edge of pavement."""
        return self.lane_width * self.lanes_each_side

    def total_half_width_flat(self) -> float:
        """Horizontal distance from centreline to shoulder break (no daylight slope)."""
        return self.pavement_half_width() + self.shoulder_width


# ---------------------------------------------------------------------------
# Cross-section point (station, offset, elevation)
# ---------------------------------------------------------------------------

@dataclass
class CrossSectionPoint:
    """A single point on a cross-section.

    Attributes
    ----------
    offset:
        Lateral offset from centreline (metres).  Positive = right.
    elevation:
        Ground-referenced elevation (metres).
    label:
        Point code label (e.g. "CL", "edge_lane_left", "shoulder_right",
        "ditch_left", "daylight_left").
    """

    offset: float
    elevation: float
    label: str = ""


@dataclass
class CrossSection:
    """One cross-section perpendicular to the alignment at a given station.

    Attributes
    ----------
    station:
        Chainage along the alignment (metres).
    cl_elevation:
        Centreline design elevation (metres).
    points:
        Ordered list of cross-section points, left to right.
    cut_area_m2:
        Cross-sectional cut area (m²).  Computed by cut_area() when terrain is
        available; 0.0 when no terrain is supplied.
    fill_area_m2:
        Cross-sectional fill area (m²).  Computed by fill_area() when terrain
        is available; 0.0 when no terrain is supplied.
    """

    station: float
    cl_elevation: float
    points: list[CrossSectionPoint] = field(default_factory=list)
    cut_area_m2: float = 0.0
    fill_area_m2: float = 0.0

    def half_section(self, side: str) -> list[CrossSectionPoint]:
        """Return points for one side ('left' or 'right')."""
        if side == "left":
            return [p for p in self.points if p.offset <= 0]
        return [p for p in self.points if p.offset >= 0]

    def cut_area(self) -> float:
        """Cross-sectional cut area (m²) — pre-computed by Corridor."""
        return self.cut_area_m2

    def fill_area(self) -> float:
        """Cross-sectional fill area (m²) — pre-computed by Corridor."""
        return self.fill_area_m2


# ---------------------------------------------------------------------------
# Terrain-aware daylight-slope intersection helpers
# ---------------------------------------------------------------------------

def _find_cut_daylight(
    hinge_offset: float,
    hinge_elev: float,
    cut_slope_h_v: float,
    side: int,
    terrain_fn: "Any",
    station: float,
    max_search_m: float = 200.0,
    step_m: float = 0.1,
) -> tuple[float, float]:
    """Find daylight for a CUT section.

    The cut backslope rises at 1 V per cut_slope_h_v H away from CL.
    Starting at the hinge point, we step outward; the design elevation
    INCREASES at rate 1/cut_slope_h_v per horizontal metre.
    Daylight occurs when design_z >= terrain_z.

    Returns (daylight_offset, daylight_elev).
    """
    n_steps = int(max_search_m / step_m) + 1
    prev_offset = hinge_offset
    prev_design = hinge_elev

    for i in range(1, n_steps + 1):
        horiz = i * step_m
        curr_offset = hinge_offset + side * horiz
        curr_design = hinge_elev + horiz / cut_slope_h_v   # rises outward in cut

        terrain_z = terrain_fn(curr_offset, station)
        if terrain_z is None:
            break

        if curr_design >= terrain_z:
            # Intersected
            prev_terrain = terrain_fn(prev_offset, station)
            if prev_terrain is None:
                return (curr_offset, terrain_z)
            # Linear interpolation
            prev_diff = prev_design - prev_terrain   # < 0 at start (design below terrain)
            curr_diff = curr_design - terrain_z      # >= 0 at daylight
            denom = curr_diff - prev_diff
            if abs(denom) < 1e-12:
                t = 0.5
            else:
                t = -prev_diff / denom
            t = max(0.0, min(1.0, t))
            interp_offset = prev_offset + side * step_m * t
            interp_elev = prev_design + (curr_design - prev_design) * t
            return (interp_offset, interp_elev)

        prev_offset = curr_offset
        prev_design = curr_design

    # Did not daylight — return limit
    limit_offset = hinge_offset + side * max_search_m
    limit_elev = hinge_elev + max_search_m / cut_slope_h_v
    return (limit_offset, limit_elev)


def _find_fill_daylight(
    hinge_offset: float,
    hinge_elev: float,
    fill_slope_h_v: float,
    side: int,
    terrain_fn: "Any",
    station: float,
    max_search_m: float = 200.0,
    step_m: float = 0.1,
) -> tuple[float, float]:
    """Find daylight for a FILL section.

    The fill foreslope descends at 1 V per fill_slope_h_v H away from CL.
    Starting at the hinge point (design above terrain), we step outward;
    the design elevation DECREASES.  Daylight when design_z <= terrain_z.

    Returns (daylight_offset, daylight_elev).
    """
    n_steps = int(max_search_m / step_m) + 1
    prev_offset = hinge_offset
    prev_design = hinge_elev

    for i in range(1, n_steps + 1):
        horiz = i * step_m
        curr_offset = hinge_offset + side * horiz
        curr_design = hinge_elev - horiz / fill_slope_h_v   # descends outward in fill

        terrain_z = terrain_fn(curr_offset, station)
        if terrain_z is None:
            break

        if curr_design <= terrain_z:
            # Intersected
            prev_terrain = terrain_fn(prev_offset, station)
            if prev_terrain is None:
                return (curr_offset, terrain_z)
            prev_diff = prev_design - prev_terrain   # > 0 at start (design above terrain)
            curr_diff = curr_design - terrain_z      # <= 0 at daylight
            denom = prev_diff - curr_diff
            if abs(denom) < 1e-12:
                t = 0.5
            else:
                t = prev_diff / denom
            t = max(0.0, min(1.0, t))
            interp_offset = prev_offset + side * step_m * t
            interp_elev = prev_design + (curr_design - prev_design) * t
            return (interp_offset, interp_elev)

        prev_offset = curr_offset
        prev_design = curr_design

    # Did not daylight — return limit
    limit_offset = hinge_offset + side * max_search_m
    limit_elev = hinge_elev - max_search_m / fill_slope_h_v
    return (limit_offset, limit_elev)


# ---------------------------------------------------------------------------
# Cross-section area computation (shoelace / signed area)
# ---------------------------------------------------------------------------

def _polygon_area(pts: list[tuple[float, float]]) -> float:
    """Signed area of a polygon via the shoelace formula.

    Parameters
    ----------
    pts : list of (x, y) — polygon vertices in order (not closed).

    Returns
    -------
    float — signed area (positive = CCW winding).
    """
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return area / 2.0


def _compute_cut_fill_areas(
    design_pts: list[tuple[float, float]],
    terrain_pts: list[tuple[float, float]],
) -> tuple[float, float]:
    """Compute cut and fill areas between design and terrain cross-section lines.

    Both lists are (offset, elevation) pairs ordered left-to-right.  The
    design subgrade polygon and the terrain surface polygon are intersected to
    partition the cross-sectional area into cut (design below terrain) and fill
    (design above terrain) zones.

    Algorithm (AASHTO GDPS-4-M §2.2.3)
    ------------------------------------
    Compute signed area of:
      cut polygon  = region where terrain > design
      fill polygon = region where design > terrain

    For each pair of adjacent design points, if the terrain is above design,
    that horizontal strip contributes to cut area; if terrain is below design,
    it contributes to fill area.  Intersections are interpolated.

    Parameters
    ----------
    design_pts  : [(offset, elev)] — design cross-section, left to right
    terrain_pts : [(offset, elev)] — terrain at same offsets, left to right

    Returns
    -------
    (cut_m2, fill_m2)  both positive.
    """
    cut_area = 0.0
    fill_area = 0.0

    n = len(design_pts)
    for i in range(n - 1):
        off0, d0 = design_pts[i]
        off1, d1 = design_pts[i + 1]
        t0, t1 = terrain_pts[i][1], terrain_pts[i + 1][1]

        diff0 = t0 - d0   # > 0 → cut (terrain above design)
        diff1 = t1 - d1

        dx = off1 - off0  # horizontal width of strip

        if diff0 >= 0 and diff1 >= 0:
            # Entire strip is cut
            cut_area += 0.5 * (diff0 + diff1) * dx
        elif diff0 <= 0 and diff1 <= 0:
            # Entire strip is fill
            fill_area += 0.5 * (-diff0 + -diff1) * dx
        else:
            # Mixed strip — find the crossover x
            # Linear interpolation: diff(x) = diff0 + (diff1-diff0)*t, t in [0,1]
            t_cross = diff0 / (diff0 - diff1)  # safe: diff0 and diff1 have different signs
            x_cross = t_cross  # fraction of dx

            if diff0 > 0:
                # Cut on left, fill on right
                cut_area += 0.5 * diff0 * t_cross * dx
                fill_area += 0.5 * (-diff1) * (1.0 - t_cross) * dx
            else:
                # Fill on left, cut on right
                fill_area += 0.5 * (-diff0) * t_cross * dx
                cut_area += 0.5 * diff1 * (1.0 - t_cross) * dx

    return (abs(cut_area), abs(fill_area))


# ---------------------------------------------------------------------------
# Corridor
# ---------------------------------------------------------------------------

@dataclass
class Corridor:
    """3-D corridor — a parametric cross-section template swept along an alignment.

    The corridor sweeps a ``TypicalSection`` (point-coded assembly: centreline,
    edge-lane, shoulder, optional ditch, side-slopes to daylight) at every
    requested station along the combined horizontal + vertical alignment.

    When *terrain* is supplied (a ``TIN`` object from ``kerf_civil.tin``),
    the daylight points are computed by intersecting the design cut/fill
    side-slope against the terrain surface.  Without terrain, a flat ground
    plane at the shoulder break elevation is assumed.

    Parameters
    ----------
    h_alignment:
        A ``HorizontalAlignment`` (or any object with ``total_length()`` and
        ``coords_at_station(s)`` methods).
    v_alignment:
        A ``VerticalAlignment`` with ``elev_at_station(s)`` method.
    typical_section:
        The standard cross-section template.
    terrain:
        Optional TIN surface for daylight computation.  Must be imported from
        ``kerf_civil.tin``.
    daylight_step_m:
        Step size (metres) for the iterative daylight-slope search.
        Smaller = more accurate, slower.  Default 0.1 m.
    """

    h_alignment: object  # HorizontalAlignment (avoid circular import)
    v_alignment: object  # VerticalAlignment
    typical_section: TypicalSection = field(default_factory=TypicalSection)
    terrain: "Any" = field(default=None)
    daylight_step_m: float = 0.1

    def _terrain_z_at(self, offset_from_cl: float, station: float) -> "float | None":
        """Interpolate terrain elevation at a lateral offset from CL at *station*.

        Uses ``kerf_civil.tin.interpolate_z`` with the world (x, y) of the
        perpendicular cross-section; falls back to None when terrain is absent
        or the point is outside the TIN extent.
        """
        if self.terrain is None:
            return None
        try:
            from kerf_civil.tin import interpolate_z
        except ImportError:
            return None

        # Get world (x, y) of the offset point
        try:
            cx, cy = self.h_alignment.coords_at_station(station)
            ds = 0.1
            L = self.h_alignment.total_length()
            s1 = min(station + ds, L)
            s0 = max(station - ds, 0.0)
            x1, y1 = self.h_alignment.coords_at_station(s1)
            x0, y0 = self.h_alignment.coords_at_station(s0)
            bearing = math.atan2(y1 - y0, x1 - x0)
        except (AttributeError, TypeError):
            cx, cy = float(station), 0.0
            bearing = 0.0

        perp_x = -math.sin(bearing)
        perp_y = math.cos(bearing)
        wx = cx + offset_from_cl * perp_x
        wy = cy + offset_from_cl * perp_y
        return interpolate_z(self.terrain, wx, wy)

    def cross_section_at(self, station: float) -> CrossSection:
        """Compute the design cross-section at *station*.

        The full point-coded assembly is computed:
          CL → edge_lane → shoulder → [ditch] → daylight
        on each side.  Daylight is found by intersecting the cut or fill
        side-slope against the terrain (or the flat shoulder plane if no
        terrain is supplied).

        Cut/fill areas are computed using the shoelace formula when terrain
        is available; set to 0.0 otherwise.

        Parameters
        ----------
        station : float
            Chainage along the alignment (metres).

        Returns
        -------
        CrossSection
        """
        cl_elev = self.v_alignment.elev_at_station(station)
        ts = self.typical_section
        crown = ts.crown_slope_pct / 100.0
        sh_slope = ts.shoulder_slope_pct / 100.0

        design_pts: list[tuple[float, float]] = []  # (offset, elev) for cut/fill area
        terrain_pts: list[tuple[float, float]] = []  # matching terrain points

        left_pts: list[CrossSectionPoint] = []
        right_pts: list[CrossSectionPoint] = []

        for sign, side, pts_list in [(-1, "left", left_pts), (1, "right", right_pts)]:
            pw = ts.pavement_half_width()
            sw = ts.shoulder_width

            # --- Edge of travel lane ---
            e_lane_offset = sign * pw
            e_lane_elev = cl_elev - crown * pw   # falls away from CL

            # --- Edge of shoulder (hinge point) ---
            e_shoulder_offset = sign * (pw + sw)
            e_shoulder_elev = e_lane_elev - sh_slope * sw  # shoulder falls away

            # --- Ditch (optional) ---
            if ts.ditch_width > 0.0:
                # Ditch inner edge = shoulder break
                # Ditch outer edge (ditch bottom)
                ditch_inner_offset = e_shoulder_offset
                ditch_inner_elev = e_shoulder_elev
                ditch_bottom_offset = sign * (pw + sw + ts.ditch_width)
                ditch_bottom_elev = e_shoulder_elev - ts.ditch_depth
                # Daylight starts from the outer ditch edge
                hinge_offset = ditch_bottom_offset
                hinge_elev = ditch_bottom_elev
                has_ditch = True
            else:
                hinge_offset = e_shoulder_offset
                hinge_elev = e_shoulder_elev
                has_ditch = False

            # --- Determine cut or fill at hinge ---
            terrain_at_hinge = self._terrain_z_at(hinge_offset, station)

            if terrain_at_hinge is not None:
                # Cut: terrain above design hinge → side-slope runs up into hillside
                # Fill: terrain below design hinge → foreslope runs down to existing grade
                is_cut = terrain_at_hinge >= hinge_elev
            else:
                # No terrain — assume cut (use cut slope for daylight approximation)
                is_cut = True

            # --- Daylight point ---
            if self.terrain is None:
                # Flat ground model: daylight at the hinge (no side-slope extension)
                daylight_offset = hinge_offset
                daylight_elev = hinge_elev
            elif is_cut:
                # Cut: side-slope runs up at cut_slope H:V; daylight when slope ≥ terrain
                # We invert the logic: step outward; design rises at 1/cut_slope per H;
                # find where design slope meets or exceeds terrain.
                daylight_offset, daylight_elev = _find_cut_daylight(
                    hinge_offset, hinge_elev,
                    ts.cut_slope, sign,
                    self._terrain_z_at, station,
                    step_m=self.daylight_step_m,
                )
            else:
                # Fill: foreslope descends outward at fill_slope H:V to terrain
                daylight_offset, daylight_elev = _find_fill_daylight(
                    hinge_offset, hinge_elev,
                    ts.fill_slope, sign,
                    self._terrain_z_at, station,
                    step_m=self.daylight_step_m,
                )

            # --- Assemble this side's points ---
            if side == "left":
                pts_list.append(CrossSectionPoint(daylight_offset, daylight_elev, f"daylight_left"))
                if has_ditch:
                    pts_list.append(CrossSectionPoint(ditch_bottom_offset, ditch_bottom_elev, "ditch_left"))
                    pts_list.append(CrossSectionPoint(ditch_inner_offset, ditch_inner_elev, "shoulder_left"))
                else:
                    pts_list.append(CrossSectionPoint(e_shoulder_offset, e_shoulder_elev, "shoulder_left"))
                pts_list.append(CrossSectionPoint(e_lane_offset, e_lane_elev, "edge_lane_left"))
            else:
                pts_list.append(CrossSectionPoint(e_lane_offset, e_lane_elev, "edge_lane_right"))
                if has_ditch:
                    pts_list.append(CrossSectionPoint(ditch_inner_offset, ditch_inner_elev, "shoulder_right"))
                    pts_list.append(CrossSectionPoint(ditch_bottom_offset, ditch_bottom_elev, "ditch_right"))
                else:
                    pts_list.append(CrossSectionPoint(e_shoulder_offset, e_shoulder_elev, "shoulder_right"))
                pts_list.append(CrossSectionPoint(daylight_offset, daylight_elev, "daylight_right"))

            # Collect design and terrain points for this side (for cut/fill area)
            if side == "left":
                design_pts_side = [(0.0, cl_elev), (e_lane_offset, e_lane_elev),
                                   (e_shoulder_offset, e_shoulder_elev), (daylight_offset, daylight_elev)]
                design_pts = design_pts_side + design_pts[:]
            else:
                design_pts = design_pts + [(0.0, cl_elev), (e_lane_offset, e_lane_elev),
                                            (e_shoulder_offset, e_shoulder_elev), (daylight_offset, daylight_elev)]

        # Assemble full cross-section: left (reversed) + CL + right
        cl_pt = CrossSectionPoint(0.0, cl_elev, "CL")
        all_pts = left_pts + [cl_pt] + right_pts

        # --- Compute cut/fill areas when terrain is available ---
        cut_m2 = 0.0
        fill_m2 = 0.0
        if self.terrain is not None:
            # Build matching terrain point list at same offsets as design
            d_offsets_elevs: list[tuple[float, float]] = []
            t_offsets_elevs: list[tuple[float, float]] = []
            for pt in all_pts:
                t_z = self._terrain_z_at(pt.offset, station)
                if t_z is not None:
                    d_offsets_elevs.append((pt.offset, pt.elevation))
                    t_offsets_elevs.append((pt.offset, t_z))
            if len(d_offsets_elevs) >= 2:
                cut_m2, fill_m2 = _compute_cut_fill_areas(d_offsets_elevs, t_offsets_elevs)

        return CrossSection(
            station=station,
            cl_elevation=cl_elev,
            points=all_pts,
            cut_area_m2=cut_m2,
            fill_area_m2=fill_m2,
        )

    def cross_sections(self, interval: float = 20.0) -> list[CrossSection]:
        """Return a list of cross-sections at a fixed *interval* (metres)."""
        L = self.h_alignment.total_length()
        sections: list[CrossSection] = []
        s = 0.0
        while s <= L + 1e-9:
            sections.append(self.cross_section_at(min(s, L)))
            s += interval
        if abs(sections[-1].station - L) > 1e-6:
            sections.append(self.cross_section_at(L))
        return sections

    def surface_points(self, interval: float = 20.0) -> list[tuple[float, float, float]]:
        """Return (station, offset, elevation) triples for all cross-section points.

        Useful for downstream 3-D mesh generation or visualisation.
        """
        result: list[tuple[float, float, float]] = []
        for xs in self.cross_sections(interval):
            for pt in xs.points:
                result.append((xs.station, pt.offset, pt.elevation))
        return result

    # --- B-rep swept road body (GK-P35) ------------------------------------

    def _xs_to_3d_pts(
        self,
        xs: "CrossSection",
        station: float,
    ) -> "list[tuple[float, float, float]]":
        """Convert a cross-section to 3-D (x, y, z) world coordinates.

        Uses ``h_alignment.coords_at_station(station)`` when available;
        falls back to ``(station, 0)`` for simple straight alignments.
        The cross-section offset is rotated by the alignment tangent bearing.
        """
        import math as _math
        try:
            cx, cy = self.h_alignment.coords_at_station(station)
            # Bearing at this station: approximate by finite difference
            ds = 0.1
            L = self.h_alignment.total_length()
            s1 = min(station + ds, L)
            s0 = max(station - ds, 0.0)
            x1, y1 = self.h_alignment.coords_at_station(s1)
            x0, y0 = self.h_alignment.coords_at_station(s0)
            bearing = _math.atan2(y1 - y0, x1 - x0)
        except (AttributeError, TypeError):
            # Straight alignment: station along X
            cx, cy = float(station), 0.0
            bearing = 0.0

        cos_b, sin_b = _math.cos(bearing), _math.sin(bearing)
        # Perpendicular to bearing (right-hand side = positive offset)
        perp_x = -sin_b
        perp_y =  cos_b

        pts3d = []
        for pt in xs.points:
            wx = cx + pt.offset * perp_x
            wy = cy + pt.offset * perp_y
            wz = pt.elevation
            pts3d.append((wx, wy, wz))
        return pts3d

    def to_brep(self, interval: float = 20.0) -> "Any":
        """Build a swept B-rep ``Body`` representing the road corridor.

        Connects successive cross-sections with quad/triangular faces to form
        a closed solid body:

        1. Top surface: triangulated from adjacent cross-section point pairs.
        2. No bottom face (corridor is an open surface body by default —
           suitable for earthwork rendering and volume computation).
        3. End caps: first and last cross-section polygons closed as planar faces.

        For a full subgrade solid, call :meth:`subgrade_brep` instead.

        Returns a ``Body`` from ``kerf_cad_core.geom.brep``.

        Raises ``ImportError`` if ``kerf_cad_core`` is not available.

        # TODO(GK-P09): wall/roof join with non-axis-aligned boolean when
        #               GK-P09 general boolean is available — currently the
        #               corridor is emitted as an open shell without junction
        #               boolean operations.
        """
        try:
            from kerf_cad_core.geom.brep import (  # type: ignore
                Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex, Line3, Plane,
            )
        except ImportError as exc:
            raise ImportError(f"kerf_cad_core not available: {exc}") from exc

        sections = self.cross_sections(interval)
        if len(sections) < 2:
            raise ValueError("corridor.to_brep requires at least 2 stations")

        # Convert all cross-sections to 3-D point lists
        xs_pts: list[list[tuple[float, float, float]]] = []
        for xs in sections:
            pts3d = self._xs_to_3d_pts(xs, xs.station)
            if pts3d:
                xs_pts.append(pts3d)

        if len(xs_pts) < 2:
            raise ValueError("corridor.to_brep: insufficient 3D cross-section data")

        import numpy as np

        def _face(pts_np):
            n = len(pts_np)
            coedges = []
            for i in range(n):
                p0, p1 = pts_np[i], pts_np[(i + 1) % n]
                v0, v1 = Vertex(p0), Vertex(p1)
                e = Edge(Line3(p0=p0, p1=p1), 0.0, 1.0, v0, v1)
                coedges.append(Coedge(edge=e, orientation=True))
            loop = Loop(coedges=coedges, is_outer=True)
            xa = pts_np[1] - pts_np[0]; nrm = np.linalg.norm(xa)
            if nrm > 1e-14: xa /= nrm
            ya = pts_np[2] - pts_np[0]
            surf = Plane(origin=pts_np[0], x_axis=xa, y_axis=ya)
            return Face(surface=surf, loops=[loop], orientation=True)

        faces: list[Any] = []

        # Top surface: for each pair of adjacent stations, connect points
        n_pts = min(len(xs_pts[0]), len(xs_pts[1]))
        for si in range(len(xs_pts) - 1):
            pts_a = [np.array(p, dtype=float) for p in xs_pts[si][:n_pts]]
            pts_b = [np.array(p, dtype=float) for p in xs_pts[si + 1][:n_pts]]
            # Create quad/triangle faces between cross-section strips
            for pi in range(len(pts_a) - 1):
                a0, a1 = pts_a[pi], pts_a[pi + 1]
                b0, b1 = pts_b[pi], pts_b[pi + 1]
                # Quad = 2 triangles
                try:
                    faces.append(_face([a0, a1, b1, b0]))
                except Exception:
                    pass

        # End caps: first and last cross-section as planar faces
        for xs_p in [xs_pts[0], xs_pts[-1]]:
            pts_cap = [np.array(p, dtype=float) for p in xs_p]
            if len(pts_cap) >= 3:
                try:
                    faces.append(_face(pts_cap))
                except Exception:
                    pass

        if not faces:
            raise ValueError("corridor.to_brep: no faces generated")

        shell = Shell(faces=faces, is_closed=False)  # open shell (top surface + end caps)
        body = Body(shells=[shell])
        return body

    def volume(self, interval: float = 20.0) -> float:
        """Estimate the pavement volume (m³) using prismatoid integration.

        Integrates the cross-sectional area (pavement half-width × 2 × lane
        thickness) along the alignment.  The lane depth is assumed 0.5 m for
        the full pavement including base course.

        This is a simplified geometric estimate; for earthwork volumes use
        :func:`kerf_civil.earthwork.prismatoid_volume` instead.

        Returns
        -------
        float
            Approximate road body volume in m³.
        """
        LANE_DEPTH_M = 0.5  # pavement + base course depth (m)
        sections = self.cross_sections(interval)
        if len(sections) < 2:
            return 0.0

        total = 0.0
        for i in range(len(sections) - 1):
            s0 = sections[i].station
            s1 = sections[i + 1].station
            ds = s1 - s0
            # Width at each station (shoulder edge to shoulder edge)
            pts0 = sections[i].points
            pts1 = sections[i + 1].points
            if pts0 and pts1:
                w0 = max(abs(p.offset) for p in pts0) * 2.0
                w1 = max(abs(p.offset) for p in pts1) * 2.0
                # Prismatoid: average cross-section area × length
                area_avg = 0.5 * (w0 + w1) * LANE_DEPTH_M
                total += area_avg * ds
        return total

    def earthwork_volumes(self, interval: float = 20.0) -> dict:
        """Compute cut/fill earthwork volumes vs the existing terrain using
        the average-end-area method (AASHTO GDPS-4-M §2.2.3).

        Requires *terrain* to be set.  Without terrain, all volumes are 0.0.

        Parameters
        ----------
        interval : float
            Station interval for cross-sections (metres).

        Returns
        -------
        dict with keys:
          ``total_cut_m3``  — total cut volume (m³, positive)
          ``total_fill_m3`` — total fill volume (m³, positive)
          ``net_m3``        — fill − cut (positive = net fill, negative = net cut)
          ``sections``      — list of per-station dicts with
                              {station_m, cut_area_m2, fill_area_m2}
        """
        from kerf_civil.earthwork import average_end_area_volume_variable

        sections = self.cross_sections(interval)
        stations = [xs.station for xs in sections]
        cut_areas = [xs.cut_area_m2 for xs in sections]
        fill_areas = [xs.fill_area_m2 for xs in sections]

        total_cut = average_end_area_volume_variable(cut_areas, stations)
        total_fill = average_end_area_volume_variable(fill_areas, stations)

        return {
            "total_cut_m3":  round(total_cut, 3),
            "total_fill_m3": round(total_fill, 3),
            "net_m3":        round(total_fill - total_cut, 3),
            "sections": [
                {
                    "station_m":    round(xs.station, 3),
                    "cut_area_m2":  round(xs.cut_area_m2, 4),
                    "fill_area_m2": round(xs.fill_area_m2, 4),
                }
                for xs in sections
            ],
        }

    def mass_haul_data(self, interval: float = 20.0, swell_factor: float = 1.25) -> list:
        """Compute the mass haul (Brückner) curve.

        Parameters
        ----------
        interval     : Station sampling interval (metres).
        swell_factor : Volume expansion factor for excavated material.
                       Typical: 1.25 for common earth (AASHTO).

        Returns
        -------
        list of dicts, each with:
          ``station_m``        — chainage (m)
          ``cut_vol_m3``       — cumulative cut volume to this station
          ``fill_vol_m3``      — cumulative fill volume to this station
          ``mass_ordinate_m3`` — Brückner mass ordinate
                                 (positive = excess / waste, negative = deficit / borrow)
        """
        from kerf_civil.earthwork import mass_haul

        sections = self.cross_sections(interval)
        stations = [xs.station for xs in sections]
        cut_areas = [xs.cut_area_m2 for xs in sections]
        fill_areas = [xs.fill_area_m2 for xs in sections]

        mh = mass_haul(stations, cut_areas, fill_areas, swell_factor)
        return [
            {
                "station_m":        round(o.station, 3),
                "cut_vol_m3":       round(o.cut_vol, 3),
                "fill_vol_m3":      round(o.fill_vol, 3),
                "mass_ordinate_m3": round(o.mass_ordinate, 3),
            }
            for o in mh
        ]

    def corridor_strings(self, interval: float = 20.0) -> dict:
        """Return 3-D feature-line strings (corridor strings) for each point code.

        Each string is a sequence of (x, y, z) world coordinates tracing one
        coded point (e.g. all "CL" points, all "daylight_right" points, etc.)
        along the alignment.

        Parameters
        ----------
        interval : float
            Station sampling interval (metres).

        Returns
        -------
        dict mapping string label → list of (x, y, z) world-coordinate tuples.
        """
        sections = self.cross_sections(interval)

        # Collect all point-code labels from the first section
        if not sections:
            return {}
        labels = [pt.label for pt in sections[0].points]
        # Ensure all sections contribute a consistent set of labels
        strings: dict[str, list[tuple[float, float, float]]] = {lbl: [] for lbl in labels}

        for xs in sections:
            pts3d = self._xs_to_3d_pts(xs, xs.station)
            for i, pt in enumerate(xs.points):
                if pt.label in strings and i < len(pts3d):
                    strings[pt.label].append(pts3d[i])

        return strings

    def ifc_alignment_dict(self) -> dict:
        """Return a minimal ``IfcAlignmentProduct`` dict for IFC export.

        Returns
        -------
        dict
            ``{"type": "IfcAlignmentProduct", "total_length": ..., ...}``
        """
        L = self.h_alignment.total_length()
        ts = self.typical_section
        return {
            "type":              "IfcAlignmentProduct",
            "total_length_m":    L,
            "lane_width_m":      ts.lane_width,
            "shoulder_width_m":  ts.shoulder_width,
            "lanes_each_side":   ts.lanes_each_side,
            "cut_slope_h_v":     ts.cut_slope,
            "fill_slope_h_v":    ts.fill_slope,
            "crown_slope_pct":   ts.crown_slope_pct,
        }
