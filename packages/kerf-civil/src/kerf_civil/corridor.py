"""
Corridor model — sweep a typical cross-section along a horizontal alignment
to produce a series of cross-sections and a 3-D corridor surface.

This module is deliberately pure-Python (no NumPy dependency) so it can be
imported in any environment.  For numerical work, callers can convert the
returned point lists to numpy arrays.

Terminology (AASHTO)
--------------------
  BL / BR  — edge of travel lane (left/right)
  SL / SR  — shoulder edge (left/right)
  DTW      — ditch toe of the slope (top of embankment or bottom of cut)

A TypicalSection defines widths and slopes; the Corridor sweeps it at
requested stations to produce a CrossSection list.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Typical section definition
# ---------------------------------------------------------------------------

@dataclass
class TypicalSection:
    """Simple symmetric two-lane typical section.

    Parameters
    ----------
    lane_width:
        Width of a single travel lane (metres).
    shoulder_width:
        Width of the shoulder (metres).
    cut_slope:
        Cut backslope ratio (H:V).  E.g. 2.0 means 2 horizontal : 1 vertical.
    fill_slope:
        Fill foreslope ratio (H:V).
    lanes_each_side:
        Number of lanes each side of the centreline.
    crown_slope_pct:
        Normal crown (cross-fall) slope, percent.  Positive = falls away
        from centreline.
    """

    lane_width: float = 3.65
    shoulder_width: float = 2.4
    cut_slope: float = 2.0
    fill_slope: float = 2.0
    lanes_each_side: int = 1
    crown_slope_pct: float = 2.0

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
        Optional label (e.g. "CL", "edge_lane", "shoulder", "daylight").
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
    """

    station: float
    cl_elevation: float
    points: list[CrossSectionPoint] = field(default_factory=list)

    def half_section(self, side: str) -> list[CrossSectionPoint]:
        """Return points for one side ('left' or 'right')."""
        if side == "left":
            return [p for p in self.points if p.offset <= 0]
        return [p for p in self.points if p.offset >= 0]

    def cut_area(self) -> float:
        """Approximate cut area (m²) using the shoelace formula on the subgrade polygon.

        Returns the cross-sectional area of material to be removed (positive for cut).
        Only valid when a ground surface is available — for the simplified
        corridor model (no DTM) this returns 0.0.
        """
        return 0.0

    def fill_area(self) -> float:
        """Approximate fill area (m²) — see cut_area notes."""
        return 0.0


# ---------------------------------------------------------------------------
# Corridor
# ---------------------------------------------------------------------------

@dataclass
class Corridor:
    """3-D corridor — a typical section swept along a horizontal alignment.

    The corridor computes design cross-sections at requested stations.  It
    does **not** require a ground DTM; daylight points are computed using
    the design subgrade only (flat natural ground at the centreline elevation
    is assumed when no DTM is supplied).

    Parameters
    ----------
    h_alignment:
        A ``HorizontalAlignment`` (or any object with a ``total_length()`` method).
    v_alignment:
        A ``VerticalAlignment`` with an ``elev_at_station(s)`` method.
    typical_section:
        The standard cross-section template.
    """

    h_alignment: object  # HorizontalAlignment (avoid circular import)
    v_alignment: object  # VerticalAlignment
    typical_section: TypicalSection = field(default_factory=TypicalSection)

    def cross_section_at(self, station: float) -> CrossSection:
        """Compute the design cross-section at *station*.

        The cross-section is constructed using the typical section geometry
        and the design profile elevation at the centreline.

        Superelevation rotation is not applied in this baseline implementation
        (normal crown only).
        """
        cl_elev = self.v_alignment.elev_at_station(station)
        ts = self.typical_section
        crown = ts.crown_slope_pct / 100.0

        points: list[CrossSectionPoint] = []

        for sign, side in [(-1, "left"), (1, "right")]:
            pw = ts.pavement_half_width()
            sw = ts.shoulder_width
            # Edge of lane
            e_lane = sign * pw
            e_lane_elev = cl_elev - crown * pw  # falls away from CL
            # Edge of shoulder
            e_shoulder = sign * (pw + sw)
            e_shoulder_elev = e_lane_elev - crown * sw

            # Daylight point — simplified: assume flat ground at shoulder break elev
            # Slope: cut or fill decided by sign of subgrade cut-depth (always cut here)
            slope = ts.cut_slope
            # For a flat natural ground model: daylight offset = shoulder break
            e_daylight = e_shoulder
            e_daylight_elev = e_shoulder_elev

            if side == "left":
                points.insert(0, CrossSectionPoint(e_daylight, e_daylight_elev, f"daylight_{side}"))
                points.insert(1, CrossSectionPoint(e_shoulder, e_shoulder_elev, f"shoulder_{side}"))
                points.insert(2, CrossSectionPoint(e_lane, e_lane_elev, f"edge_lane_{side}"))
            else:
                points.append(CrossSectionPoint(e_lane, e_lane_elev, f"edge_lane_{side}"))
                points.append(CrossSectionPoint(e_shoulder, e_shoulder_elev, f"shoulder_{side}"))
                points.append(CrossSectionPoint(e_daylight, e_daylight_elev, f"daylight_{side}"))

        # Centreline point inserted in the middle
        cl_idx = len(points) // 2
        points.insert(cl_idx, CrossSectionPoint(0.0, cl_elev, "CL"))

        return CrossSection(station=station, cl_elevation=cl_elev, points=points)

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
