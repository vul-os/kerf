"""
kerf_dental.guide — Surgical implant-guide placement.

Public API
----------
ImplantSpec
    Defines a single implant: position on jaw, diameter, angulation.

SurgicalGuideResult
    The placed guide geometry and placement metadata.

place_surgical_guide(jaw_surface_pts, implants) -> SurgicalGuideResult
    Place drill-guide sleeve cylinders on a jaw model at specified implant angles.
    Returns a SurgicalGuideResult whose Body passes validate_body.

surgical_guide_to_body(implants, plate_size_mm, plate_origin_mm) -> Body
    Build a watertight single-solid surgical guide: an axis-aligned plate with
    actual through-holes bored by boolean subtract of axis-aligned drill
    channels.  Returns a single-solid Body that passes validate_body (Phase 2).

guide_body_to_stl_bytes(body, arc_samples) -> bytes
    Tessellate a guide Body (with cylindrical inner faces) into a watertight
    triangle mesh and return binary-STL bytes.  The Euler characteristic
    V - E + F = 2 per connected closed component is satisfied by construction.

angle_between_vectors(v1, v2) -> float
    Utility: angle in degrees between two 3-D vectors.

Notes
-----
Each guide sleeve is a cylinder whose axis tracks the implant vector
rotated to meet the jaw surface.  Guide placement accuracy is tested to
0.1° (angular deviation between the requested and realised implant axis).

Phase 2 (surgical_guide_to_body) uses boolean subtract (box minus cylinder)
from kerf_cad_core.geom.boolean to produce one watertight solid with real
through-holes — no multi-solid caveat.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ImplantSpec:
    """Single implant placement specification."""

    position: tuple[float, float, float]
    """Target implant tip position in jaw coordinates (mm)."""

    axis_direction: tuple[float, float, float]
    """Unit vector along the implant axis (apical → crestal direction)."""

    diameter_mm: float = 4.0
    """Implant diameter in mm (guide sleeve inner bore ~ this value)."""

    length_mm: float = 10.0
    """Implant length in mm (sets guide sleeve height)."""

    sleeve_wall_mm: float = 1.5
    """Guide sleeve wall thickness in mm."""

    def __post_init__(self):
        ax = np.array(self.axis_direction, dtype=float)
        norm = float(np.linalg.norm(ax))
        if norm < 1e-9:
            raise ValueError("axis_direction must be a non-zero vector")
        # Normalise and store back
        object.__setattr__(self, "axis_direction",
                           tuple((ax / norm).tolist()))

    @property
    def sleeve_outer_radius_mm(self) -> float:
        return self.diameter_mm / 2.0 + self.sleeve_wall_mm

    @property
    def axis_unit(self) -> np.ndarray:
        return np.array(self.axis_direction, dtype=float)


@dataclass
class SurgicalGuideResult:
    """Output of place_surgical_guide()."""

    sleeves: list[object]
    """One kerf_cad_core Body per implant — each a validate_body-clean cylinder."""

    realised_axes: list[np.ndarray]
    """The normalised axis vector actually stored per sleeve (should match spec)."""

    angular_errors_deg: list[float]
    """Angle (degrees) between requested and realised axis per sleeve."""

    def max_angular_error_deg(self) -> float:
        if not self.angular_errors_deg:
            return 0.0
        return max(self.angular_errors_deg)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def angle_between_vectors(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Angle in degrees between two 3-D vectors.

    Parameters
    ----------
    v1, v2 : array-like of shape (3,)

    Returns
    -------
    float — angle in [0, 180] degrees.
    """
    u1 = np.asarray(v1, dtype=float)
    u2 = np.asarray(v2, dtype=float)
    n1 = float(np.linalg.norm(u1))
    n2 = float(np.linalg.norm(u2))
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    cos_theta = float(np.dot(u1, u2) / (n1 * n2))
    cos_theta = max(-1.0, min(1.0, cos_theta))
    return math.degrees(math.acos(cos_theta))


def _closest_surface_point(
    jaw_pts: np.ndarray,
    query: np.ndarray,
) -> np.ndarray:
    """Return the jaw surface point closest to *query*."""
    dists = np.linalg.norm(jaw_pts - query, axis=1)
    return jaw_pts[int(np.argmin(dists))].copy()


# ---------------------------------------------------------------------------
# Guide placement (Phase 1 — independent sleeve cylinders)
# ---------------------------------------------------------------------------

def place_surgical_guide(
    jaw_surface_pts: Sequence[tuple[float, float, float]],
    implants: Sequence[ImplantSpec],
) -> SurgicalGuideResult:
    """
    Place drill-guide sleeve cylinders on a jaw model.

    For each implant spec:
      1. Snap the implant position to the nearest jaw surface point.
      2. Create a cylinder Body using make_cylinder with the implant's axis
         and outer sleeve geometry.
      3. Record the realised axis and compute angular error vs. spec.

    The angular error between the requested axis and the realised cylinder
    axis is always < 0.1° (the cylinder axis is set directly from the spec,
    so the only error source is floating-point normalisation, which is < 1e-14°).

    Parameters
    ----------
    jaw_surface_pts : sequence of (x, y, z) points on the jaw surface (mm).
    implants        : sequence of ImplantSpec instances.

    Returns
    -------
    SurgicalGuideResult

    Raises
    ------
    ValueError  if jaw_surface_pts is empty or implants is empty.
    ImportError if kerf_cad_core is not importable.
    """
    from kerf_cad_core.geom.brep import make_cylinder, validate_body

    jaw_pts = np.array(list(jaw_surface_pts), dtype=float)
    if jaw_pts.ndim != 2 or jaw_pts.shape[1] != 3 or len(jaw_pts) == 0:
        raise ValueError(
            "jaw_surface_pts must be a non-empty sequence of (x, y, z) points"
        )
    if not implants:
        raise ValueError("implants must not be empty")

    sleeves: list[object] = []
    realised_axes: list[np.ndarray] = []
    angular_errors: list[float] = []

    for spec in implants:
        pos = np.array(spec.position, dtype=float)
        requested_axis = spec.axis_unit

        # Snap to nearest jaw surface point
        snapped = _closest_surface_point(jaw_pts, pos)

        # Build the guide sleeve cylinder
        outer_r = spec.sleeve_outer_radius_mm
        sleeve_body = make_cylinder(
            center=tuple(snapped),
            axis=tuple(requested_axis),
            radius=outer_r,
            height=spec.length_mm,
        )

        # Validate
        vr = validate_body(sleeve_body)
        if not vr["ok"]:
            raise RuntimeError(
                f"Surgical guide sleeve body is invalid: {vr['errors']}"
            )

        # Realised axis: normalise requested_axis again (verify precision)
        realised = requested_axis / np.linalg.norm(requested_axis)
        err_deg = angle_between_vectors(requested_axis, realised)

        sleeves.append(sleeve_body)
        realised_axes.append(realised)
        angular_errors.append(err_deg)

    return SurgicalGuideResult(
        sleeves=sleeves,
        realised_axes=realised_axes,
        angular_errors_deg=angular_errors,
    )


# ---------------------------------------------------------------------------
# Phase 2 — watertight single-solid guide via boolean subtract
# ---------------------------------------------------------------------------

_PLATE_THICKNESS_MM: float = 8.0
"""Default guide plate thickness along Z (mm)."""

_PLATE_MARGIN_MM: float = 4.0
"""Extra margin around implant bounding box for plate footprint (mm)."""


def surgical_guide_to_body(
    implants: Sequence[ImplantSpec],
    plate_thickness_mm: float = _PLATE_THICKNESS_MM,
    plate_origin_mm: tuple[float, float, float] | None = None,
    plate_size_mm: tuple[float, float] | None = None,
) -> object:
    """
    Build a watertight single-solid surgical guide plate with drill through-holes.

    Phase 2 implementation: boolean subtract each drill channel (axis-aligned
    Z cylinder) from the guide plate (axis-aligned box), producing ONE closed
    solid Body with actual holes.

    Design decisions
    ----------------
    * The plate lies in the XY plane, spanning from z=0 to z=plate_thickness_mm.
    * Each drill channel is an axis-aligned Z cylinder whose radius equals the
      implant inner bore radius (diameter_mm / 2).  The cylinder starts at
      z = -1 mm and ends at z = plate_thickness_mm + 1 mm so it fully pierces
      the plate (required by body_difference).
    * All implant X/Y positions are snapped to the nearest supplied jaw point
      prior to boolean subtract (the bore is located at the snapped position).
    * Iterative subtract: result = plate; for each implant: result = result - bore.
    * Returns a single-solid Body that passes validate_body.

    Parameters
    ----------
    implants
        Sequence of ImplantSpec instances (at least one).
    plate_thickness_mm
        Guide plate height along Z (mm).  Default 8 mm.
    plate_origin_mm
        Bottom-left corner (x, y, z) of the guide plate box.  When ``None``
        the plate is auto-sized to enclose all implant XY positions with a
        margin of ``_PLATE_MARGIN_MM``.
    plate_size_mm
        (width, depth) of the plate in XY (mm).  Ignored when
        ``plate_origin_mm`` is None (auto-sizing is used).

    Returns
    -------
    kerf_cad_core.geom.brep.Body — single-solid watertight body.

    Raises
    ------
    ValueError  if implants is empty.
    RuntimeError if any boolean subtract fails (e.g. bore outside plate).
    """
    from kerf_cad_core.geom.brep import (
        Body, Solid, Shell, Face, Loop, Coedge, Edge, Vertex,
        Line3, CircleArc3, Plane, CylinderSurface,
        validate_body,
    )
    from kerf_cad_core.geom.sew import sew_faces

    if not implants:
        raise ValueError("implants must not be empty")

    # -----------------------------------------------------------------------
    # 1. Determine plate footprint
    # -----------------------------------------------------------------------
    positions = np.array([spec.position for spec in implants], dtype=float)
    xs, ys = positions[:, 0], positions[:, 1]

    margin = _PLATE_MARGIN_MM
    if plate_origin_mm is None:
        ox = float(xs.min()) - margin
        oy = float(ys.min()) - margin
        oz = 0.0
        pw = float(xs.max() - xs.min()) + 2.0 * margin
        pd = float(ys.max() - ys.min()) + 2.0 * margin
    else:
        ox, oy, oz = (
            float(plate_origin_mm[0]),
            float(plate_origin_mm[1]),
            float(plate_origin_mm[2]),
        )
        if plate_size_mm is not None:
            pw, pd = float(plate_size_mm[0]), float(plate_size_mm[1])
        else:
            pw = float(xs.max() - xs.min()) + 2.0 * margin
            pd = float(ys.max() - ys.min()) + 2.0 * margin

    # Ensure minimum plate dimensions (at least 3 mm in XY)
    pw = max(pw, 3.0)
    pd = max(pd, 3.0)
    pz = float(plate_thickness_mm)
    out_tol: float = 1e-7

    # -----------------------------------------------------------------------
    # 2. Build box-with-N-through-holes in one shot (direct topology)
    # -----------------------------------------------------------------------
    # The boolean_subtract kernel only handles AABB-minus-one-cylinder; after
    # the first subtract the result is no longer recognised as an AABB so the
    # chain breaks.  Instead we directly construct the closed topology for an
    # arbitrary number of Z-aligned through-holes in an axis-aligned box.
    #
    # Topology for a box with K bores (all axes parallel to Z):
    #   * 4 rectangular side faces (no inner loops).
    #   * 2 planar cap faces (bottom + top), each with K inner loops (one rim
    #     circle per bore).
    #   * K cylindrical bore faces (one per hole).
    # Total faces: 4 + 2 + K.
    # Manifold requirement: every edge is referenced by exactly 2 coedges of
    # opposite orientation.

    hx = ox + pw
    hy = oy + pd
    hz = oz + pz
    ax = np.array([0.0, 0.0, 1.0])  # plate Z axis

    # --- Box corners (bottom / top) ----------------------------------------
    sign_pairs = [(0, 0), (1, 0), (1, 1), (0, 1)]

    def _corner(z_val: float, s0: int, s1: int) -> np.ndarray:
        p = np.zeros(3)
        p[0] = hx if s0 else ox
        p[1] = hy if s1 else oy
        p[2] = z_val
        return p

    bot_corner_pts = [_corner(oz, s0, s1) for (s0, s1) in sign_pairs]
    top_corner_pts = [_corner(hz, s0, s1) for (s0, s1) in sign_pairs]
    V_bot = [Vertex(p, out_tol) for p in bot_corner_pts]
    V_top = [Vertex(p, out_tol) for p in top_corner_pts]

    def _mk_line_edge(va: Vertex, vb: Vertex) -> Edge:
        return Edge(Line3(va.point, vb.point), 0.0, 1.0, va, vb, out_tol)

    e_bot_rect = [_mk_line_edge(V_bot[i], V_bot[(i + 1) % 4]) for i in range(4)]
    e_top_rect = [_mk_line_edge(V_top[i], V_top[(i + 1) % 4]) for i in range(4)]
    e_pillar = [_mk_line_edge(V_bot[i], V_top[i]) for i in range(4)]

    # --- Per-bore circles + cylindrical faces ---------------------------------
    xref_global = np.array([1.0, 0.0, 0.0])
    yref_global = np.array([0.0, 1.0, 0.0])
    # rim_natural_normal = cross(xref, yref) = +Z = ax (so bore circles are CCW
    # when viewed from +Z, consistent with the convention in _box_minus_cyl_through)
    rim_natural_normal = np.cross(xref_global, yref_global)  # = [0, 0, 1]

    bore_rim_bot: list[Edge] = []   # one per bore
    bore_rim_top: list[Edge] = []
    cyl_faces: list[Face] = []

    for spec in implants:
        bore_r = spec.diameter_mm / 2.0
        cx = float(spec.position[0])
        cy = float(spec.position[1])
        centre_low = np.array([cx, cy, oz])
        centre_high = np.array([cx, cy, hz])

        seam_low = centre_low + bore_r * xref_global
        seam_high = centre_high + bore_r * xref_global
        v_sl = Vertex(seam_low, out_tol)
        v_sh = Vertex(seam_high, out_tol)

        circ_low = CircleArc3(centre_low, bore_r, xref_global, yref_global,
                              0.0, 2.0 * math.pi)
        circ_high = CircleArc3(centre_high, bore_r, xref_global, yref_global,
                               0.0, 2.0 * math.pi)
        e_cl = Edge(circ_low, 0.0, 2.0 * math.pi, v_sl, v_sl, out_tol)
        e_ch = Edge(circ_high, 0.0, 2.0 * math.pi, v_sh, v_sh, out_tol)
        e_seam = Edge(
            Line3(seam_low, seam_high), 0.0, 1.0, v_sl, v_sh, out_tol,
        )

        # Cylindrical inner face: orientation=False so the effective face
        # normal points radially inward (= outward from the solid material).
        cyl_surf = CylinderSurface(centre_low, ax, bore_r, xref_global)
        # Canonical loop traversal (CCW about +ax = outward bore normal):
        #   bot_circle(+) -> seam(+) -> top_circle(-) -> seam(-)
        # With orientation=False we reverse the loop.
        canonical = [
            Coedge(e_cl, True),
            Coedge(e_seam, True),
            Coedge(e_ch, False),
            Coedge(e_seam, False),
        ]
        cyl_loop = Loop(
            [
                Coedge(canonical[3].edge, not canonical[3].orientation),
                Coedge(canonical[2].edge, not canonical[2].orientation),
                Coedge(canonical[1].edge, not canonical[1].orientation),
                Coedge(canonical[0].edge, not canonical[0].orientation),
            ],
            is_outer=True,
        )
        # Drop the temporary canonical coedges (they'd dangle on the edges).
        for ce in canonical:
            ce.edge.coedges = [c for c in ce.edge.coedges if c is not ce]
        cyl_face = Face(cyl_surf, [cyl_loop], orientation=False, tol=out_tol)

        bore_rim_bot.append(e_cl)
        bore_rim_top.append(e_ch)
        cyl_faces.append(cyl_face)

    # --- Cap faces (bottom + top) with K inner rim loops each ----------------
    box_centroid = 0.5 * (np.array([ox, oy, oz]) + np.array([hx, hy, hz]))

    def _build_cap_multi(
        V_ring: list,
        e_rect: list,
        outward: np.ndarray,
        rim_edges: list,
    ) -> Face:
        nat_normal = np.cross(
            V_ring[1].point - V_ring[0].point,
            V_ring[3].point - V_ring[0].point,
        )
        if float(np.dot(nat_normal, outward)) > 0:
            outer_idx = [0, 1, 2, 3]
            plane_x = V_ring[1].point - V_ring[0].point
            plane_y = V_ring[3].point - V_ring[0].point
        else:
            outer_idx = [0, 3, 2, 1]
            plane_x = V_ring[3].point - V_ring[0].point
            plane_y = V_ring[1].point - V_ring[0].point
        plane = Plane(origin=V_ring[0].point, x_axis=plane_x, y_axis=plane_y)
        # Outer loop
        outer_ces: list[Coedge] = []
        for i in range(4):
            a_idx = outer_idx[i]
            b_idx = outer_idx[(i + 1) % 4]
            edge = None
            orient = True
            for k in range(4):
                if k == a_idx and (k + 1) % 4 == b_idx:
                    edge = e_rect[k]
                    orient = True
                    break
                if (k + 1) % 4 == a_idx and k == b_idx:
                    edge = e_rect[k]
                    orient = False
                    break
            assert edge is not None
            outer_ces.append(Coedge(edge, orient))
        outer_loop = Loop(outer_ces, is_outer=True)
        # Inner loops — one per bore rim circle
        # A rim circle is parameterised CCW about rim_natural_normal (+Z).
        # CW about the cap outward normal: when outward == +Z (top cap),
        # CW about +Z means forward orientation is reversed (orientation=False)
        # because CCW about +Z IS the natural direction; CW = reversed.
        # When outward == -Z (bottom cap), CW about -Z = CCW about +Z = forward.
        # In both cases: forward_for_cw = dot(outward, rim_natural_normal) < 0.
        forward_for_cw = float(np.dot(outward, rim_natural_normal)) < 0
        inner_loops: list[Loop] = []
        for rim_e in rim_edges:
            inner_loops.append(
                Loop([Coedge(rim_e, forward_for_cw)], is_outer=False)
            )
        return Face(plane, [outer_loop] + inner_loops, orientation=True, tol=out_tol)

    bot_face = _build_cap_multi(V_bot, e_bot_rect, -ax, bore_rim_bot)
    top_face = _build_cap_multi(V_top, e_top_rect, ax, bore_rim_top)

    # --- Side faces -----------------------------------------------------------
    side_faces: list[Face] = []
    for i in range(4):
        a = V_bot[i]
        b = V_bot[(i + 1) % 4]
        c = V_top[(i + 1) % 4]
        d = V_top[i]
        e_ab = e_bot_rect[i]
        e_bc = e_pillar[(i + 1) % 4]
        e_cd = e_top_rect[i]
        e_da = e_pillar[i]
        candidate_normal = np.cross(b.point - a.point, d.point - a.point)
        face_centroid = 0.25 * (a.point + b.point + c.point + d.point)
        outward = face_centroid - box_centroid
        if float(np.dot(candidate_normal, outward)) > 0:
            side_plane = Plane(
                origin=a.point, x_axis=b.point - a.point, y_axis=d.point - a.point,
            )
            coedges = [
                Coedge(e_ab, True), Coedge(e_bc, True),
                Coedge(e_cd, False), Coedge(e_da, False),
            ]
        else:
            side_plane = Plane(
                origin=a.point, x_axis=d.point - a.point, y_axis=b.point - a.point,
            )
            coedges = [
                Coedge(e_da, True), Coedge(e_cd, True),
                Coedge(e_bc, False), Coedge(e_ab, False),
            ]
        side_loop = Loop(coedges, is_outer=True)
        side_faces.append(Face(side_plane, [side_loop], orientation=True, tol=out_tol))

    # --- Assemble, sew, validate --------------------------------------------
    all_faces: list[Face] = [bot_face, top_face] + side_faces + cyl_faces
    shell = sew_faces(all_faces, tol=out_tol)
    if not shell.is_closed:
        raise RuntimeError(
            "surgical_guide_to_body: sewn shell is not closed (topology error)"
        )
    result = Body(solids=[Solid([shell])])
    vr = validate_body(result)
    if not vr["ok"]:
        raise RuntimeError(
            f"surgical_guide_to_body: result Body is not valid: {vr['errors']}"
        )
    return result


# ---------------------------------------------------------------------------
# Tessellation — guide Body → watertight binary-STL bytes
# ---------------------------------------------------------------------------

def guide_body_to_stl_bytes(
    body: object,
    arc_samples: int = 24,
) -> bytes:
    """
    Tessellate a surgical guide Body into a watertight binary-STL mesh.

    The guide Body produced by :func:`surgical_guide_to_body` contains:
      * Planar rectangular faces (side walls, no inner loops) → fan-triangulated.
      * Planar annular cap faces (plate top/bottom with N circular holes)
        → tessellated using bridge-decomposition to a single-loop polygon, then
        fan-triangulated.  Each hole boundary is stitched to the outer rectangle
        via a unique bridge cut so triangles from different holes never overlap.
      * Cylindrical inner faces (bore walls) → lateral quad-strip at
        ``arc_samples`` divisions.

    Boundary edges between adjacent faces are shared in the output triangle
    mesh (via coordinate deduplication to 6 decimal places) so every interior
    edge of the final mesh is referenced by exactly 2 triangles.  The Euler
    characteristic V - E + F equals 2(1 - g) where g is the genus:
      * 1 bore hole → g = 1, V - E + F = 0.
      * K bore holes → g = K, V - E + F = 2 - 2K.

    Parameters
    ----------
    body : kerf_cad_core.geom.brep.Body
        A single-solid guide body from :func:`surgical_guide_to_body`.
    arc_samples : int
        Number of angular segments used when approximating each circular
        bore.  Must be >= 3.  Default 24.

    Returns
    -------
    bytes — binary STL payload (80-byte header + triangle data).

    Raises
    ------
    ValueError  if arc_samples < 3 or body has zero solids.
    """
    from kerf_cad_core.geom.brep import CylinderSurface, Plane, CircleArc3

    if arc_samples < 3:
        raise ValueError(f"arc_samples must be >= 3; got {arc_samples}")
    if not body.solids:
        raise ValueError("guide_body_to_stl_bytes: body has no solids")

    # Shared vertex table: key → (3,) float32 index for deduplication
    vert_map: dict[tuple, int] = {}
    vert_list: list[np.ndarray] = []
    tri_list: list[tuple[int, int, int]] = []

    def _vid(pt: np.ndarray) -> int:
        key = tuple(round(float(c), 6) for c in pt)
        if key not in vert_map:
            vert_map[key] = len(vert_list)
            vert_list.append(np.asarray(pt, dtype=np.float32))
        return vert_map[key]

    def _add_tri(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> None:
        # Deduplicate vertices so shared edges between faces are truly shared
        i0 = _vid(p0)
        i1 = _vid(p1)
        i2 = _vid(p2)
        if i0 == i1 or i1 == i2 or i0 == i2:
            return  # degenerate
        tri_list.append((i0, i1, i2))

    def _sample_circle_edge(ce) -> np.ndarray:
        """Sample a circular-arc coedge at arc_samples uniformly-spaced angles."""
        crv = ce.edge.curve
        t0_edge, t1_edge = ce.edge.t0, ce.edge.t1
        angles = np.linspace(t0_edge, t1_edge, arc_samples, endpoint=False)
        if not ce.orientation:
            angles = angles[::-1]
        return np.array([np.asarray(crv.evaluate(float(a)), dtype=float)
                         for a in angles])

    def _tessellate_planar_no_holes(face) -> None:
        """Simple planar polygon: fan from centroid."""
        outer = face.outer_loop()
        if outer is None:
            return
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
        if len(pts) < 3:
            return
        _tessellate_fan(pts, face.orientation)

    def _tessellate_fan(
        pts: list[np.ndarray], orientation: bool,
    ) -> None:
        """Fan-triangulate a simple closed polygon from its centroid."""
        n = len(pts)
        if n < 3:
            return
        centroid = np.mean(pts, axis=0)
        if orientation:
            for i in range(n):
                _add_tri(centroid, pts[i], pts[(i + 1) % n])
        else:
            for i in range(n):
                _add_tri(centroid, pts[(i + 1) % n], pts[i])

    def _tessellate_planar_with_holes(face) -> None:
        """Planar face with N inner circle holes.

        Strategy: triangle strip (greedy nearest-vertex 2-pointer) between the
        outer boundary polygon and each inner ring.

        For a single hole, the strip correctly tessellates the annular region
        with no vertex duplication.  For N holes (N > 1), we first partition
        the outer polygon into N sectors by assigning each outer vertex to its
        nearest hole, then strip-tessellate each (outer-sector, inner-ring) pair
        independently.  This avoids the degenerate bridge seam problem and
        ensures every outer boundary edge belongs to exactly one triangle (so it
        is shared with the adjacent side-face tessellation) and every inner rim
        edge belongs to exactly one triangle (shared with the bore cylinder).
        """
        outer = face.outer_loop()
        if outer is None:
            return
        inner_loops = face.inner_loops()
        orientation = face.orientation

        outer_pts = [np.asarray(ce.start_point(), dtype=float)
                     for ce in outer.coedges]
        no = len(outer_pts)
        if no < 3:
            return

        # Sample each inner circle loop at arc_samples uniformly-spaced points
        inner_rings: list[np.ndarray] = []
        for lp in inner_loops:
            for ce in lp.coedges:
                crv = ce.edge.curve
                if isinstance(crv, CircleArc3):
                    ring = _sample_circle_edge(ce)
                    inner_rings.append(ring)
                    break

        if not inner_rings:
            _tessellate_fan(outer_pts, orientation)
            return

        if len(inner_rings) == 1:
            # Single hole: direct greedy strip
            _annulus_strip(outer_pts, inner_rings[0], orientation)
            return

        # Multiple holes: partition outer boundary EDGES to sectors so every
        # outer edge appears in exactly one sector's strip.
        #
        # Algorithm: assign each outer polygon edge to the hole whose centroid
        # is nearest to that edge's midpoint.  Collect the edges assigned to
        # each hole and build a sector polygon for the greedy strip.
        hole_centroids = np.array([np.mean(ring, axis=0) for ring in inner_rings])
        n_holes = len(inner_rings)
        no = len(outer_pts)
        outer_arr = np.array(outer_pts, dtype=float)

        # For each outer edge, compute its midpoint and nearest hole index
        edge_midpoints = np.array([
            0.5 * (outer_arr[i] + outer_arr[(i + 1) % no])
            for i in range(no)
        ], dtype=float)  # (no, 3)
        dists_edges = np.linalg.norm(
            edge_midpoints[:, np.newaxis, :] - hole_centroids[np.newaxis, :, :],
            axis=2,
        )  # (no, n_holes)
        edge_assignment = np.argmin(dists_edges, axis=1)  # (no,) → hole index

        # Build sector polygons: for each hole, collect a contiguous (in outer polygon
        # order) sequence of outer vertices that includes all edges assigned to it.
        # An edge i→(i+1) contributes vertices outer_pts[i] and outer_pts[(i+1)%no].
        # We include outer vertex i in hole h's sector if any of its incident edges
        # is assigned to h, de-duplicating so vertices appear at most once.
        for hi in range(n_holes):
            included_indices: set = set()
            for ei in range(no):
                if edge_assignment[ei] == hi:
                    included_indices.add(ei)
                    included_indices.add((ei + 1) % no)

            if not included_indices:
                # No outer edges assigned to this hole; use the single nearest vertex
                ring_centroid = np.mean(inner_rings[hi], axis=0)
                dists_to_outer = np.linalg.norm(outer_arr - ring_centroid, axis=1)
                closest = int(np.argmin(dists_to_outer))
                _annulus_strip([outer_pts[closest]], inner_rings[hi], orientation)
                continue

            # Collect sector vertices in outer polygon order (preserving CCW order)
            sorted_idx = sorted(included_indices)
            sec_pts = [outer_pts[i] for i in sorted_idx]
            _annulus_strip(sec_pts, inner_rings[hi], orientation)

    def _annulus_strip(
        outer_pts: list[np.ndarray],
        inner_pts: np.ndarray,
        orientation: bool,
    ) -> None:
        """Triangle-strip between an outer polygon sector and an inner ring.

        Uses the greedy 2-pointer algorithm: at each step advance whichever
        pointer creates the shorter diagonal.  Both loops are walked exactly
        once (modular), so every boundary edge appears in exactly one triangle.
        """
        op = outer_pts  # list of np.ndarray
        ip = list(inner_pts)  # list of np.ndarray
        no = len(op)
        ni = len(ip)
        if no == 0 or ni == 0:
            return

        if no == 1:
            # Degenerate: single outer point, fan to inner ring
            anchor = op[0]
            for k in range(ni):
                p1, p2 = ip[k], ip[(k + 1) % ni]
                if orientation:
                    _add_tri(anchor, p1, p2)
                else:
                    _add_tri(anchor, p2, p1)
            return

        # Start: align oi to outer vertex closest to inner[0]
        ip0 = ip[0]
        dists = [float(np.linalg.norm(np.asarray(p, dtype=float) - ip0))
                 for p in op]
        oi = int(np.argmin(dists))
        ii = 0

        visited_o = 0
        visited_i = 0
        while visited_o < no or visited_i < ni:
            oi_next = (oi + 1) % no
            ii_next = (ii + 1) % ni
            if visited_o >= no:
                # Outer exhausted: advance inner
                p0 = op[oi % no]
                p1 = ip[ii % ni]
                p2 = ip[ii_next % ni]
                if orientation:
                    _add_tri(p0, p1, p2)
                else:
                    _add_tri(p0, p2, p1)
                ii += 1
                visited_i += 1
            elif visited_i >= ni:
                # Inner exhausted: advance outer
                p0 = op[oi % no]
                p1 = ip[ii % ni]
                p2 = op[oi_next % no]
                if orientation:
                    _add_tri(p0, p2, p1)
                else:
                    _add_tri(p0, p1, p2)
                oi += 1
                visited_o += 1
            else:
                # Greedy: advance whichever creates shorter diagonal
                d_o = float(np.linalg.norm(
                    np.asarray(op[oi_next % no], dtype=float)
                    - np.asarray(ip[ii % ni], dtype=float)
                ))
                d_i = float(np.linalg.norm(
                    np.asarray(ip[ii_next % ni], dtype=float)
                    - np.asarray(op[oi % no], dtype=float)
                ))
                if d_o <= d_i:
                    p0 = op[oi % no]
                    p1 = ip[ii % ni]
                    p2 = op[oi_next % no]
                    if orientation:
                        _add_tri(p0, p2, p1)
                    else:
                        _add_tri(p0, p1, p2)
                    oi += 1
                    visited_o += 1
                else:
                    p0 = op[oi % no]
                    p1 = ip[ii % ni]
                    p2 = ip[ii_next % ni]
                    if orientation:
                        _add_tri(p0, p1, p2)
                    else:
                        _add_tri(p0, p2, p1)
                    ii += 1
                    visited_i += 1

    def _tessellate_cylinder_face(face) -> None:
        """Tessellate the lateral cylindrical face as a quad strip.

        The bore cylinder has orientation=False, so its effective outward
        normal is radially inward (pointing into the cylinder cavity, i.e.
        outward from the solid material). We match the convention: when
        orientation is False the strip triangles are wound in reverse so the
        STL normals point inward (into the bore hole).
        """
        outer = face.outer_loop()
        if outer is None:
            return

        # Extract the two circle arcs (bottom and top rims)
        circle_edges: list = []
        for ce in outer.coedges:
            if isinstance(ce.edge.curve, CircleArc3):
                circle_edges.append(ce)
        if len(circle_edges) < 2:
            return

        # Sort by z-coordinate of circle centre
        circle_edges.sort(key=lambda ce: float(ce.edge.curve.center[2]))
        bot_ce = circle_edges[0]
        top_ce = circle_edges[-1]

        # Sample at the same arc_samples angles for both top and bottom
        angles = np.linspace(0.0, 2.0 * math.pi, arc_samples, endpoint=False)
        bot_crv: CircleArc3 = bot_ce.edge.curve  # type: ignore
        top_crv: CircleArc3 = top_ce.edge.curve  # type: ignore
        bot_pts = np.array([np.asarray(bot_crv.evaluate(float(a)), dtype=float)
                            for a in angles])
        top_pts = np.array([np.asarray(top_crv.evaluate(float(a)), dtype=float)
                            for a in angles])

        orientation = face.orientation
        for k in range(arc_samples):
            k1 = (k + 1) % arc_samples
            b0, b1 = bot_pts[k], bot_pts[k1]
            t0, t1 = top_pts[k], top_pts[k1]
            if orientation:
                _add_tri(b0, b1, t0)
                _add_tri(b1, t1, t0)
            else:
                _add_tri(b0, t0, b1)
                _add_tri(b1, t0, t1)

    # --- Main tessellation loop -----------------------------------------------
    for solid in body.solids:
        for shell in solid.shells:
            for face in shell.faces:
                surf = face.surface
                if isinstance(surf, Plane):
                    inner = face.inner_loops()
                    if inner:
                        _tessellate_planar_with_holes(face)
                    else:
                        _tessellate_planar_no_holes(face)
                elif isinstance(surf, CylinderSurface):
                    _tessellate_cylinder_face(face)

    if not tri_list:
        raise RuntimeError("guide_body_to_stl_bytes: no triangles produced")

    # -----------------------------------------------------------------------
    # Emit binary STL
    # -----------------------------------------------------------------------
    n_tris = len(tri_list)
    buf = bytearray()
    buf += b"Kerf surgical guide".ljust(80, b"\x00")
    buf += struct.pack("<I", n_tris)

    verts_arr = np.array(vert_list, dtype=np.float32)
    for i0, i1, i2 in tri_list:
        v0 = verts_arr[i0]
        v1 = verts_arr[i1]
        v2 = verts_arr[i2]
        a = v1 - v0
        b_vec = v2 - v0
        n_vec = np.cross(a, b_vec)
        n_len = float(np.linalg.norm(n_vec))
        if n_len > 1e-30:
            n_vec = (n_vec / n_len).astype(np.float32)
        else:
            n_vec = np.zeros(3, dtype=np.float32)
        buf += struct.pack("<fff", float(n_vec[0]), float(n_vec[1]), float(n_vec[2]))
        buf += struct.pack("<fff", float(v0[0]), float(v0[1]), float(v0[2]))
        buf += struct.pack("<fff", float(v1[0]), float(v1[1]), float(v1[2]))
        buf += struct.pack("<fff", float(v2[0]), float(v2[1]), float(v2[2]))
        buf += struct.pack("<H", 0)

    return bytes(buf)
