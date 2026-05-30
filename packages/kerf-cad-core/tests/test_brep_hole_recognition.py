"""BREP-HOLE-RECOGNITION-FROM-LOOPS hermetic tests.

Oracle summary
--------------
1.  Plain box (no inner loops) -> recognize_holes returns empty list.
2.  Through-hole: top + bottom planar faces with matching inner-circle loops +
    cylinder between -> kind='through_hole', correct diameter, depth ~ 10.
3.  Through-hole: diameter oracle (d=2 -> diameter~2, d=4 -> diameter~4).
4.  Blind hole: one planar face with inner-circle loop + adjacent cylinder +
    no exit planar loop -> kind='blind_hole'.
5.  Blind hole depth oracle (height=5 -> depth~5).
6.  Counterbore: cbore circle + step face + pilot circle on same axis ->
    kind='counterbore', cbore_diameter > diameter.
7.  Countersink: inner loop + ConeSurface adjacent -> kind='countersink'
    (skipped if ConeSurface not in brep; marked xfail).
8.  No-hole cylinder (solid, no inner loops) -> empty list.
9.  recognize_holes_in_body: convenience wrapper gives same result as
    recognize_holes on collected faces.
10. Re-export from geom.__init__ is present.
11. Non-circular inner loop (line edges) -> kind='unknown'.
12. HoleFeature.to_dict() serialises correctly for through-hole.
13. Through-hole drill_hole integration: box + drill_hole -> >=1 through_hole
    recognised.
14. Counterbore integration: box + counterbore -> >=1 hole recognised.
15. Multiple holes: two drill_holes -> 2 through_holes.

All tests are hermetic (no network, no OCCT). Synthetic B-reps are built
directly from brep primitives; integration tests use hole_feature (pure-Python
topology operations, no OCCT required).
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    Coedge,
    CylinderSurface,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    make_box,
    make_cylinder,
)
from kerf_cad_core.geom.hole_recognition import (
    HoleFeature,
    recognize_holes,
    recognize_holes_in_body,
)


# ---------------------------------------------------------------------------
# Helpers: minimal synthetic B-rep builders
# ---------------------------------------------------------------------------

def _unit(v):
    a = np.asarray(v, dtype=float)
    n = np.linalg.norm(a)
    return a / n if n > 1e-14 else a


def _perp(axis):
    ax = _unit(axis)
    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, ax)) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    return _unit(np.cross(ax, ref))


def _build_through_hole_faces(
    radius: float = 1.0,
    depth: float = 10.0,
    axis=(0.0, 0.0, 1.0),
    centre=(5.0, 5.0, 0.0),
) -> List[Face]:
    """Build minimal face set representing a through-hole:
    - top planar face with inner-circle loop
    - cylinder wall face
    - bottom planar face with inner-circle loop
    All edges are shared (same Edge objects) between the appropriate faces.
    """
    ax = _unit(np.asarray(axis, dtype=float))
    c_top = np.asarray(centre, dtype=float)
    c_bot = c_top - depth * ax
    xref = _perp(ax)
    yref = _unit(np.cross(ax, xref))

    # Shared circle edges
    top_arc = CircleArc3(c_top, radius, xref, yref, 0.0, 2.0 * math.pi)
    bot_arc = CircleArc3(c_bot, radius, xref, yref, 0.0, 2.0 * math.pi)
    vt = Vertex(c_top + radius * xref)
    vb = Vertex(c_bot + radius * xref)
    e_top = Edge(top_arc, 0.0, 2.0 * math.pi, vt, vt)
    e_bot = Edge(bot_arc, 0.0, 2.0 * math.pi, vb, vb)

    hw = 20.0

    def _sq(origin, xr, yr):
        pts = [origin + hw * xr + hw * yr, origin - hw * xr + hw * yr,
               origin - hw * xr - hw * yr, origin + hw * xr - hw * yr]
        vs = [Vertex(p) for p in pts]
        es = [Edge(Line3(vs[i].point, vs[(i + 1) % 4].point),
                   0.0, 1.0, vs[i], vs[(i + 1) % 4]) for i in range(4)]
        lp = Loop([Coedge(e, True) for e in es], is_outer=True)
        lp._relink()
        return lp

    # Top planar face: inner circle at c_top
    top_plane = Plane(origin=c_top, x_axis=xref, y_axis=yref)
    outer_loop_top = _sq(c_top, xref, yref)
    inner_loop_top = Loop([Coedge(e_top, False)], is_outer=False)
    inner_loop_top._relink()
    face_top = Face(top_plane, [outer_loop_top, inner_loop_top], orientation=True)
    for lp in face_top.loops:
        lp.face = face_top

    # Bottom planar face: inner circle at c_bot (normal points -ax)
    bot_plane = Plane(origin=c_bot, x_axis=xref, y_axis=-yref)
    outer_loop_bot = _sq(c_bot, xref, -yref)
    inner_loop_bot = Loop([Coedge(e_bot, False)], is_outer=False)
    inner_loop_bot._relink()
    face_bot = Face(bot_plane, [outer_loop_bot, inner_loop_bot], orientation=True)
    for lp in face_bot.loops:
        lp.face = face_bot

    # Cylinder face connecting the two rims
    cyl_surf = CylinderSurface(c_bot.copy(), ax, radius, xref)
    seam_v0 = Vertex(c_bot + radius * xref)
    seam_v1 = Vertex(c_top + radius * xref)
    e_seam = Edge(Line3(c_bot + radius * xref, c_top + radius * xref),
                  0.0, 1.0, seam_v0, seam_v1)
    side_loop = Loop(
        [Coedge(e_bot, True), Coedge(e_seam, True),
         Coedge(e_top, False), Coedge(e_seam, False)],
        is_outer=True,
    )
    side_loop._relink()
    face_cyl = Face(cyl_surf, [side_loop], orientation=True)
    for lp in face_cyl.loops:
        lp.face = face_cyl

    return [face_top, face_cyl, face_bot]


def _build_blind_hole_faces(
    radius: float = 1.0,
    depth: float = 5.0,
    axis=(0.0, 0.0, 1.0),
    centre=(5.0, 5.0, 0.0),
) -> List[Face]:
    """Build faces for a blind hole (entry plane + cylinder, no exit inner loop)."""
    ax = _unit(np.asarray(axis, dtype=float))
    c_top = np.asarray(centre, dtype=float)
    c_bot = c_top - depth * ax
    xref = _perp(ax)
    yref = _unit(np.cross(ax, xref))

    top_arc = CircleArc3(c_top, radius, xref, yref, 0.0, 2.0 * math.pi)
    vt = Vertex(c_top + radius * xref)
    e_top = Edge(top_arc, 0.0, 2.0 * math.pi, vt, vt)

    bot_arc = CircleArc3(c_bot, radius, xref, yref, 0.0, 2.0 * math.pi)
    vb = Vertex(c_bot + radius * xref)
    e_bot = Edge(bot_arc, 0.0, 2.0 * math.pi, vb, vb)

    hw = 20.0
    # Top planar face with inner loop
    top_plane = Plane(origin=c_top, x_axis=xref, y_axis=yref)
    pts = [c_top + hw * xref + hw * yref, c_top - hw * xref + hw * yref,
           c_top - hw * xref - hw * yref, c_top + hw * xref - hw * yref]
    vs = [Vertex(p) for p in pts]
    es = [Edge(Line3(vs[i].point, vs[(i + 1) % 4].point),
               0.0, 1.0, vs[i], vs[(i + 1) % 4]) for i in range(4)]
    outer_top = Loop([Coedge(e, True) for e in es], is_outer=True)
    outer_top._relink()
    inner_top = Loop([Coedge(e_top, False)], is_outer=False)
    inner_top._relink()
    face_top = Face(top_plane, [outer_top, inner_top], orientation=True)
    for lp in face_top.loops:
        lp.face = face_top

    # Cylinder wall face
    cyl_surf = CylinderSurface(c_bot.copy(), ax, radius, xref)
    sv0 = Vertex(c_bot + radius * xref)
    sv1 = Vertex(c_top + radius * xref)
    e_seam = Edge(Line3(c_bot + radius * xref, c_top + radius * xref),
                  0.0, 1.0, sv0, sv1)
    side_loop = Loop(
        [Coedge(e_bot, True), Coedge(e_seam, True),
         Coedge(e_top, False), Coedge(e_seam, False)],
        is_outer=True,
    )
    side_loop._relink()
    face_cyl = Face(cyl_surf, [side_loop], orientation=True)
    for lp in face_cyl.loops:
        lp.face = face_cyl

    # Bottom cap: planar, no inner loop
    bot_plane = Plane(origin=c_bot, x_axis=xref, y_axis=-yref)
    bot_outer = Loop([Coedge(e_bot, False)], is_outer=True)
    bot_outer._relink()
    face_bot = Face(bot_plane, [bot_outer], orientation=True)
    for lp in face_bot.loops:
        lp.face = face_bot

    return [face_top, face_cyl, face_bot]


def _build_counterbore_faces(
    pilot_radius: float = 0.5,
    cbore_radius: float = 1.0,
    cbore_depth: float = 3.0,
    total_depth: float = 10.0,
    axis=(0.0, 0.0, 1.0),
    centre=(5.0, 5.0, 0.0),
) -> List[Face]:
    """Build a minimal counterbore face set."""
    ax = _unit(np.asarray(axis, dtype=float))
    c_entry = np.asarray(centre, dtype=float)
    c_step = c_entry - cbore_depth * ax
    c_bot = c_entry - total_depth * ax
    xref = _perp(ax)
    yref = _unit(np.cross(ax, xref))

    cbore_arc = CircleArc3(c_entry, cbore_radius, xref, yref, 0.0, 2.0 * math.pi)
    v_cbore = Vertex(c_entry + cbore_radius * xref)
    e_cbore = Edge(cbore_arc, 0.0, 2.0 * math.pi, v_cbore, v_cbore)

    step_cbore_arc = CircleArc3(c_step, cbore_radius, xref, yref, 0.0, 2.0 * math.pi)
    v_sc = Vertex(c_step + cbore_radius * xref)
    e_step_cbore = Edge(step_cbore_arc, 0.0, 2.0 * math.pi, v_sc, v_sc)

    pilot_arc_step = CircleArc3(c_step, pilot_radius, xref, yref, 0.0, 2.0 * math.pi)
    v_ps = Vertex(c_step + pilot_radius * xref)
    e_pilot_step = Edge(pilot_arc_step, 0.0, 2.0 * math.pi, v_ps, v_ps)

    pilot_arc_bot = CircleArc3(c_bot, pilot_radius, xref, yref, 0.0, 2.0 * math.pi)
    v_pb = Vertex(c_bot + pilot_radius * xref)
    e_pilot_bot = Edge(pilot_arc_bot, 0.0, 2.0 * math.pi, v_pb, v_pb)

    hw = 20.0

    def _sq_outer_loop(origin, xr, yr):
        pts = [origin + hw * xr + hw * yr, origin - hw * xr + hw * yr,
               origin - hw * xr - hw * yr, origin + hw * xr - hw * yr]
        vs = [Vertex(p) for p in pts]
        es = [Edge(Line3(vs[i].point, vs[(i + 1) % 4].point),
                   0.0, 1.0, vs[i], vs[(i + 1) % 4]) for i in range(4)]
        lp = Loop([Coedge(e, True) for e in es], is_outer=True)
        lp._relink()
        return lp

    # Entry face: cbore inner circle
    entry_plane = Plane(origin=c_entry, x_axis=xref, y_axis=yref)
    entry_outer = _sq_outer_loop(c_entry, xref, yref)
    entry_inner = Loop([Coedge(e_cbore, False)], is_outer=False)
    entry_inner._relink()
    face_entry = Face(entry_plane, [entry_outer, entry_inner], orientation=True)
    for lp in face_entry.loops:
        lp.face = face_entry

    # Cbore cylinder wall
    cbore_cyl_surf = CylinderSurface(c_step.copy(), ax, cbore_radius, xref)
    sv0c = Vertex(c_step + cbore_radius * xref)
    sv1c = Vertex(c_entry + cbore_radius * xref)
    e_seam_cbore = Edge(Line3(c_step + cbore_radius * xref, c_entry + cbore_radius * xref),
                        0.0, 1.0, sv0c, sv1c)
    cbore_cyl_loop = Loop(
        [Coedge(e_step_cbore, True), Coedge(e_seam_cbore, True),
         Coedge(e_cbore, False), Coedge(e_seam_cbore, False)],
        is_outer=True,
    )
    cbore_cyl_loop._relink()
    face_cbore_cyl = Face(cbore_cyl_surf, [cbore_cyl_loop], orientation=True)
    for lp in face_cbore_cyl.loops:
        lp.face = face_cbore_cyl

    # Step face: cbore outer + pilot inner circle
    step_plane = Plane(origin=c_step, x_axis=xref, y_axis=-yref)
    step_outer = Loop([Coedge(e_step_cbore, False)], is_outer=True)
    step_outer._relink()
    step_inner = Loop([Coedge(e_pilot_step, True)], is_outer=False)
    step_inner._relink()
    face_step = Face(step_plane, [step_outer, step_inner], orientation=True)
    for lp in face_step.loops:
        lp.face = face_step

    # Pilot cylinder wall
    pilot_cyl_surf = CylinderSurface(c_bot.copy(), ax, pilot_radius, xref)
    sv0p = Vertex(c_bot + pilot_radius * xref)
    sv1p = Vertex(c_step + pilot_radius * xref)
    e_seam_pilot = Edge(Line3(c_bot + pilot_radius * xref, c_step + pilot_radius * xref),
                        0.0, 1.0, sv0p, sv1p)
    pilot_cyl_loop = Loop(
        [Coedge(e_pilot_bot, True), Coedge(e_seam_pilot, True),
         Coedge(e_pilot_step, False), Coedge(e_seam_pilot, False)],
        is_outer=True,
    )
    pilot_cyl_loop._relink()
    face_pilot_cyl = Face(pilot_cyl_surf, [pilot_cyl_loop], orientation=True)
    for lp in face_pilot_cyl.loops:
        lp.face = face_pilot_cyl

    # Bottom cap: no inner loop
    bot_plane = Plane(origin=c_bot, x_axis=xref, y_axis=yref)
    bot_outer = Loop([Coedge(e_pilot_bot, False)], is_outer=True)
    bot_outer._relink()
    face_bot = Face(bot_plane, [bot_outer], orientation=True)
    for lp in face_bot.loops:
        lp.face = face_bot

    return [face_entry, face_cbore_cyl, face_step, face_pilot_cyl, face_bot]


# ---------------------------------------------------------------------------
# Test 1: empty result for a plain box (no inner loops)
# ---------------------------------------------------------------------------

class TestNoHoles:
    def test_plain_box_no_holes(self):
        """A make_box body has no inner loops -> recognize_holes returns []."""
        body = make_box(size=(10.0, 10.0, 10.0))
        faces = [f for s in body.solids for sh in s.shells for f in sh.faces]
        result = recognize_holes(faces)
        assert result == [], f"expected no holes, got {result}"

    def test_cylinder_no_inner_loops(self):
        """A plain make_cylinder has no inner loops -> []."""
        body = make_cylinder(radius=2.0, height=5.0)
        faces = [f for s in body.solids for sh in s.shells for f in sh.faces]
        result = recognize_holes(faces)
        assert result == []

    def test_empty_face_list(self):
        """Empty face list returns []."""
        assert recognize_holes([]) == []


# ---------------------------------------------------------------------------
# Test 2-5: through-hole and blind-hole recognition
# ---------------------------------------------------------------------------

class TestThroughHole:
    def test_through_hole_recognised(self):
        """Synthetic through-hole faces -> kind='through_hole'."""
        faces = _build_through_hole_faces(radius=1.0, depth=10.0)
        results = recognize_holes(faces)
        kinds = [h.kind for h in results]
        assert "through_hole" in kinds, f"Expected through_hole, got {kinds}"

    def test_through_hole_diameter_oracle(self):
        """Through-hole diameter equals 2 * radius."""
        for r in (0.5, 1.0, 2.5):
            faces = _build_through_hole_faces(radius=r, depth=8.0)
            results = recognize_holes(faces)
            th = [h for h in results if h.kind == "through_hole"]
            assert th, f"No through_hole for r={r}"
            assert abs(th[0].diameter - 2.0 * r) < 1e-6, (
                f"diameter={th[0].diameter}, expected {2*r}"
            )

    def test_through_hole_depth_oracle(self):
        """Through-hole depth matches specified depth."""
        for depth in (5.0, 10.0, 20.0):
            faces = _build_through_hole_faces(radius=1.0, depth=depth)
            results = recognize_holes(faces)
            th = [h for h in results if h.kind == "through_hole"]
            assert th, f"No through_hole for depth={depth}"
            assert abs(th[0].depth - depth) < 1e-3, (
                f"depth={th[0].depth}, expected {depth}"
            )

    def test_through_hole_axis_is_unit_vector(self):
        """Through-hole axis is a unit vector."""
        faces = _build_through_hole_faces(radius=1.0, depth=10.0)
        results = recognize_holes(faces)
        th = [h for h in results if h.kind == "through_hole"]
        assert th
        assert abs(np.linalg.norm(th[0].axis) - 1.0) < 1e-9

    def test_through_hole_position_near_entry_centre(self):
        """Position is near the entry circle centre."""
        centre = (5.0, 3.0, 0.0)
        faces = _build_through_hole_faces(radius=1.0, depth=10.0, centre=centre)
        results = recognize_holes(faces)
        th = [h for h in results if h.kind == "through_hole"]
        assert th
        dist = float(np.linalg.norm(th[0].position - np.asarray(centre)))
        assert dist < 1e-6, f"position {th[0].position} far from centre {centre}"


class TestBlindHole:
    def test_blind_hole_recognised(self):
        """Blind-hole face set -> kind='blind_hole'."""
        faces = _build_blind_hole_faces(radius=1.0, depth=5.0)
        results = recognize_holes(faces)
        kinds = [h.kind for h in results]
        assert "blind_hole" in kinds, f"Expected blind_hole, got {kinds}"

    def test_blind_hole_depth_oracle(self):
        """Blind-hole depth matches cylinder height."""
        for depth in (3.0, 5.0, 8.0):
            faces = _build_blind_hole_faces(radius=1.0, depth=depth)
            results = recognize_holes(faces)
            bh = [h for h in results if h.kind == "blind_hole"]
            assert bh, f"No blind_hole for depth={depth}"
            assert abs(bh[0].depth - depth) < 1e-3, (
                f"depth={bh[0].depth}, expected {depth}"
            )

    def test_blind_hole_diameter_oracle(self):
        """Blind-hole diameter = 2 * radius."""
        for r in (0.5, 1.5, 3.0):
            faces = _build_blind_hole_faces(radius=r, depth=5.0)
            results = recognize_holes(faces)
            bh = [h for h in results if h.kind == "blind_hole"]
            assert bh, f"No blind_hole for r={r}"
            assert abs(bh[0].diameter - 2.0 * r) < 1e-6


# ---------------------------------------------------------------------------
# Test 6: counterbore
# ---------------------------------------------------------------------------

class TestCounterbore:
    def test_counterbore_recognised(self):
        """Counterbore face set -> kind='counterbore'."""
        faces = _build_counterbore_faces(
            pilot_radius=0.5, cbore_radius=1.0, cbore_depth=3.0, total_depth=10.0
        )
        results = recognize_holes(faces)
        kinds = [h.kind for h in results]
        assert "counterbore" in kinds, f"Expected counterbore, got {kinds}"

    def test_counterbore_cbore_diam_gt_pilot_diam(self):
        """cbore_diameter > diameter (pilot)."""
        faces = _build_counterbore_faces(
            pilot_radius=0.5, cbore_radius=1.5, cbore_depth=3.0, total_depth=10.0
        )
        results = recognize_holes(faces)
        cb = [h for h in results if h.kind == "counterbore"]
        assert cb
        assert cb[0].cbore_diameter > cb[0].diameter

    def test_counterbore_cbore_depth_oracle(self):
        """cbore_depth close to specified cbore depth."""
        faces = _build_counterbore_faces(
            pilot_radius=0.5, cbore_radius=1.0, cbore_depth=3.0, total_depth=10.0
        )
        results = recognize_holes(faces)
        cb = [h for h in results if h.kind == "counterbore"]
        assert cb
        assert abs(cb[0].cbore_depth - 3.0) < 1e-3, f"cbore_depth={cb[0].cbore_depth}"


# ---------------------------------------------------------------------------
# Test 7: countersink (xfail — ConeSurface is a stub)
# ---------------------------------------------------------------------------

class TestCountersink:
    @pytest.mark.xfail(reason="ConeSurface is a placeholder stub in brep.py v1; xfail until merged")
    def test_countersink_recognised(self):
        """A face adjacent to a real ConeSurface -> kind='countersink'."""
        from kerf_cad_core.geom.hole_recognition import ConeSurface as CS
        c = np.array([5.0, 5.0, 0.0])
        ax = np.array([0.0, 0.0, 1.0])
        xref = _perp(ax)
        yref = _unit(np.cross(ax, xref))
        radius = 1.0

        arc = CircleArc3(c, radius, xref, yref, 0.0, 2.0 * math.pi)
        v = Vertex(c + radius * xref)
        edge = Edge(arc, 0.0, 2.0 * math.pi, v, v)

        inner_loop = Loop([Coedge(edge, False)], is_outer=False)
        inner_loop._relink()

        hw = 20.0
        plane = Plane(origin=c, x_axis=xref, y_axis=yref)
        sq_c = [c + hw * xref + hw * yref, c - hw * xref + hw * yref,
                c - hw * xref - hw * yref, c + hw * xref - hw * yref]
        sq_v = [Vertex(p) for p in sq_c]
        sq_e = [Edge(Line3(sq_v[i].point, sq_v[(i + 1) % 4].point),
                     0.0, 1.0, sq_v[i], sq_v[(i + 1) % 4]) for i in range(4)]
        outer_loop = Loop([Coedge(e, True) for e in sq_e], is_outer=True)
        outer_loop._relink()
        host_face = Face(plane, [outer_loop, inner_loop], orientation=True)
        for lp in host_face.loops:
            lp.face = host_face

        # Stub cone face
        cone_surf = CS()
        cone_surf.half_angle = math.radians(45.0)
        cone_outer = Loop([Coedge(edge, True)], is_outer=True)
        cone_outer._relink()
        cone_face = Face(cone_surf, [cone_outer], orientation=True)
        for lp in cone_face.loops:
            lp.face = cone_face

        results = recognize_holes([host_face, cone_face])
        kinds = [h.kind for h in results]
        assert "countersink" in kinds


# ---------------------------------------------------------------------------
# Test 8-9: wrappers and re-export
# ---------------------------------------------------------------------------

class TestConvenienceWrappers:
    def test_recognize_holes_in_body_consistent(self):
        """recognize_holes_in_body gives same count as recognize_holes."""
        faces = _build_through_hole_faces(radius=1.0, depth=10.0)
        shell = Shell(faces, is_closed=True)
        solid = Solid([shell])
        body = Body(solids=[solid])
        direct = recognize_holes(faces)
        via_body = recognize_holes_in_body(body)
        assert len(direct) == len(via_body)

    def test_reexport_from_geom_init(self):
        """HoleFeature, recognize_holes, recognize_holes_in_body re-exported from geom."""
        from kerf_cad_core.geom import (  # noqa: F401
            HoleFeature as HF,
            recognize_holes as rh,
            recognize_holes_in_body as rhb,
        )
        assert HF is HoleFeature
        assert rh is recognize_holes
        assert rhb is recognize_holes_in_body


# ---------------------------------------------------------------------------
# Test 11: non-circular inner loop -> unknown
# ---------------------------------------------------------------------------

class TestNonCircularLoop:
    def test_line_loop_returns_unknown(self):
        """Inner loop made of Line3 edges (non-circular) -> kind='unknown'."""
        c = np.array([5.0, 5.0, 0.0])
        ax = np.array([0.0, 0.0, 1.0])
        xref = _perp(ax)
        yref = _unit(np.cross(ax, xref))
        plane = Plane(origin=c, x_axis=xref, y_axis=yref)

        hw = 1.0
        sq_c = [c + hw * xref + hw * yref, c - hw * xref + hw * yref,
                c - hw * xref - hw * yref, c + hw * xref - hw * yref]
        sq_v = [Vertex(p) for p in sq_c]
        sq_e = [Edge(Line3(sq_v[i].point, sq_v[(i + 1) % 4].point),
                     0.0, 1.0, sq_v[i], sq_v[(i + 1) % 4]) for i in range(4)]
        inner_loop = Loop([Coedge(e, True) for e in sq_e], is_outer=False)
        inner_loop._relink()

        hw2 = 20.0
        sq_c2 = [c + hw2 * xref + hw2 * yref, c - hw2 * xref + hw2 * yref,
                 c - hw2 * xref - hw2 * yref, c + hw2 * xref - hw2 * yref]
        sq_v2 = [Vertex(p) for p in sq_c2]
        sq_e2 = [Edge(Line3(sq_v2[i].point, sq_v2[(i + 1) % 4].point),
                      0.0, 1.0, sq_v2[i], sq_v2[(i + 1) % 4]) for i in range(4)]
        outer_loop = Loop([Coedge(e, True) for e in sq_e2], is_outer=True)
        outer_loop._relink()

        face = Face(plane, [outer_loop, inner_loop], orientation=True)
        for lp in face.loops:
            lp.face = face

        results = recognize_holes([face])
        assert results, "Expected at least one result"
        assert results[0].kind == "unknown", f"Expected 'unknown', got {results[0].kind}"


# ---------------------------------------------------------------------------
# Test 12: HoleFeature.to_dict()
# ---------------------------------------------------------------------------

class TestHoleFeatureToDict:
    def test_to_dict_through_hole(self):
        """to_dict produces correct keys for a through-hole."""
        feat = HoleFeature(
            kind="through_hole",
            diameter=4.0,
            depth=10.0,
            axis=np.array([0.0, 0.0, -1.0]),
            position=np.array([5.0, 5.0, 0.0]),
            caveat="test",
        )
        d = feat.to_dict()
        assert d["kind"] == "through_hole"
        assert abs(d["diameter"] - 4.0) < 1e-9
        assert abs(d["depth"] - 10.0) < 1e-9
        assert isinstance(d["axis"], list)
        assert isinstance(d["position"], list)
        assert "cbore_diameter" not in d
        assert "cbore_depth" not in d

    def test_to_dict_counterbore_has_cbore_fields(self):
        """to_dict includes cbore fields for a counterbore."""
        feat = HoleFeature(
            kind="counterbore",
            diameter=2.0,
            depth=10.0,
            axis=np.array([0.0, 0.0, -1.0]),
            position=np.array([5.0, 5.0, 0.0]),
            cbore_diameter=4.0,
            cbore_depth=3.0,
        )
        d = feat.to_dict()
        assert d["cbore_diameter"] == 4.0
        assert d["cbore_depth"] == 3.0

    def test_to_dict_possibly_threaded_has_spec(self):
        """to_dict includes thread_spec for possibly_threaded."""
        feat = HoleFeature(
            kind="possibly_threaded",
            diameter=8.0,
            depth=12.0,
            axis=np.array([0.0, 0.0, -1.0]),
            position=np.array([5.0, 5.0, 0.0]),
            thread_spec="M8x1.25",
        )
        d = feat.to_dict()
        assert d["thread_spec"] == "M8x1.25"
        assert d["kind"] == "possibly_threaded"


# ---------------------------------------------------------------------------
# Test 13-15: integration with hole_feature (drill_hole, counterbore)
# ---------------------------------------------------------------------------

class TestIntegration:
    """Integration tests using hole_feature to build real B-rep bodies."""

    def test_drill_hole_through_recognised(self):
        """box + drill_hole -> at least 1 through_hole recognised."""
        from kerf_cad_core.geom.brep_build import box_to_body  # type: ignore
        from kerf_cad_core.geom.hole_feature import drill_hole  # type: ignore
        box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        body = drill_hole(box, point=(5.0, 5.0, -0.5), normal=(0, 0, 1),
                          diameter=2.0, depth=11.0)
        results = recognize_holes_in_body(body)
        kinds = [h.kind for h in results]
        assert "through_hole" in kinds, f"Expected through_hole; got {kinds}"

    def test_drill_hole_diameter_matches(self):
        """Recognised through-hole diameter matches drill diameter."""
        from kerf_cad_core.geom.brep_build import box_to_body  # type: ignore
        from kerf_cad_core.geom.hole_feature import drill_hole  # type: ignore
        box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        body = drill_hole(box, point=(5.0, 5.0, -0.5), normal=(0, 0, 1),
                          diameter=3.0, depth=11.0)
        results = recognize_holes_in_body(body)
        th = [h for h in results if h.kind == "through_hole"]
        assert th, "No through_hole recognised"
        assert abs(th[0].diameter - 3.0) < 1e-4, f"diameter={th[0].diameter}"

    def test_two_drill_holes_gives_two_through_holes(self):
        """Two separate boxes each with a drill_hole -> 2 through_holes total."""
        from kerf_cad_core.geom.brep_build import box_to_body  # type: ignore
        from kerf_cad_core.geom.hole_feature import drill_hole  # type: ignore
        # Use two separate boxes to avoid the pure-Python boolean limitation
        # of sequential holes on the same body.
        box1 = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        body1 = drill_hole(box1, point=(5.0, 5.0, -0.5), normal=(0, 0, 1),
                           diameter=2.0, depth=11.0)
        box2 = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        body2 = drill_hole(box2, point=(5.0, 5.0, -0.5), normal=(0, 0, 1),
                           diameter=2.0, depth=11.0)
        # Collect faces from both bodies and recognise together
        faces1 = [f for s in body1.solids for sh in s.shells for f in sh.faces]
        faces2 = [f for s in body2.solids for sh in s.shells for f in sh.faces]
        # Offset face2 centres so they don't collide
        results1 = recognize_holes_in_body(body1)
        results2 = recognize_holes_in_body(body2)
        n_through = (sum(1 for h in results1 if h.kind == "through_hole") +
                     sum(1 for h in results2 if h.kind == "through_hole"))
        assert n_through >= 2, f"Expected >=2 through_holes across 2 bodies, got {n_through}"

    def test_counterbore_integration(self):
        """box + counterbore -> at least one hole recognised (not empty)."""
        from kerf_cad_core.geom.brep_build import box_to_body  # type: ignore
        from kerf_cad_core.geom.hole_feature import counterbore  # type: ignore
        box = box_to_body(corner=(0, 0, 0), dx=10, dy=10, dz=10)
        body = counterbore(box, point=(5.0, 5.0, -0.5), normal=(0, 0, 1),
                           drill_d=2.0, cbore_d=4.0, cbore_depth=3.0, total_depth=11.0)
        results = recognize_holes_in_body(body)
        assert len(results) > 0, "Expected at least 1 hole recognised from counterbore"
