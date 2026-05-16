"""GK-13: hermetic tests for the brep_build production bridge.

Every test is self-contained -- no network, no OCCT, no fixtures. The
suite exercises:

  * ``surface_to_face`` over the analytic adapters (``Plane`` /
    ``CylinderSurface`` / ``SphereSurface``) and over a bicubic
    ``NurbsSurface`` patch.
  * ``box_to_body`` / ``cylinder_to_body`` / ``sphere_to_body`` -- the
    production analytic primitives -- with topology counts, volume by
    triple integral, and full ``validate_body`` cleanliness.
  * ``surfaces_to_shell`` -- vertex / edge sewing on an L of two faces.
  * ``closed_shell_to_solid`` -- correct wrapping of a closed shell.
  * Determinism across 5 independent runs.
  * A deliberately-misoriented (outer-CW) face is rejected.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    validate_body,
)
from kerf_cad_core.geom.brep_build import (
    BuildError,
    box_to_body,
    closed_shell_to_solid,
    cylinder_to_body,
    sphere_to_body,
    surface_to_face,
    surfaces_to_shell,
)
from kerf_cad_core.geom.brep_build import _validate_face_local
from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# surface_to_face / analytic surfaces
# ---------------------------------------------------------------------------


def _flat_plane(width: float = 1.0, height: float = 1.0) -> Plane:
    return Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([width, 0.0, 0.0]),
        y_axis=np.array([0.0, height, 0.0]),
    )


def test_face_from_plane_natural_boundary_validates():
    f = surface_to_face(_flat_plane())
    assert isinstance(f, Face)
    assert _validate_face_local(f) == []


def test_face_from_plane_has_one_outer_loop_four_coedges():
    f = surface_to_face(_flat_plane())
    assert len(f.loops) == 1
    outer = f.outer_loop()
    assert outer is not None
    assert outer.is_outer is True
    assert len(outer.coedges) == 4


def test_face_outer_loop_is_ccw_wrt_normal():
    """Signed area projected on the surface normal must be positive."""
    from kerf_cad_core.geom.brep import _loop_signed_area_about_normal

    f = surface_to_face(_flat_plane(2.0, 3.0))
    signed = _loop_signed_area_about_normal(f.outer_loop(), f)
    assert signed is not None
    assert signed > 0.0


def test_face_outer_loop_ccw_for_negative_normal_plane():
    """Flip the plane's normal (swap x/y axes) -- builder must still
    produce a CCW outer loop with respect to the flipped normal."""
    flipped = Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([0.0, 1.0, 0.0]),
        y_axis=np.array([1.0, 0.0, 0.0]),  # normal now -z
    )
    f = surface_to_face(flipped)
    assert _validate_face_local(f) == []


def test_face_from_bicubic_nurbs_surface_validates():
    cps = np.zeros((4, 4, 3))
    for i in range(4):
        for j in range(4):
            cps[i, j] = [float(i), float(j), 0.1 * i * j]
    knots = np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=float)
    surf = NurbsSurface(
        degree_u=3, degree_v=3, control_points=cps,
        knots_u=knots, knots_v=knots,
    )
    f = surface_to_face(surf)
    assert _validate_face_local(f) == []


def test_face_from_bicubic_outer_loop_ccw():
    from kerf_cad_core.geom.brep import _loop_signed_area_about_normal

    cps = np.zeros((4, 4, 3))
    for i in range(4):
        for j in range(4):
            cps[i, j] = [float(i), float(j), 0.05 * (i * i + j * j)]
    knots = np.array([0, 0, 0, 0, 1, 1, 1, 1], dtype=float)
    surf = NurbsSurface(
        degree_u=3, degree_v=3, control_points=cps,
        knots_u=knots, knots_v=knots,
    )
    f = surface_to_face(surf)
    signed = _loop_signed_area_about_normal(f.outer_loop(), f)
    assert signed is not None
    assert signed > 0.0


def test_face_corner_vertices_match_surface_evaluations():
    """For the analytic ``Plane`` adapter, ``evaluate(u, v) = origin +
    u*unit(x) + v*unit(y)`` over the parametric box ``(0, 1) x (0, 1)``;
    the natural face corners are therefore the 4 unit-square corners on
    the plane spanned by the plane's *normalised* axes.
    """
    plane = _flat_plane(4.0, 7.0)  # axes normalised inside Plane.__post_init__
    f = surface_to_face(plane)
    starts = [ce.start_point() for ce in f.outer_loop().coedges]
    expected = {
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 1.0, 0.0),
    }
    seen = {tuple(round(c, 9) for c in p) for p in starts}
    assert seen == expected


def test_surface_to_face_explicit_curves():
    """Pass explicit boundary curves (lines) and verify face validates."""
    pts = [
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([1.0, 1.0, 0.0]),
        np.array([0.0, 1.0, 0.0]),
    ]
    curves = [Line3(pts[i], pts[(i + 1) % 4]) for i in range(4)]
    f = surface_to_face(_flat_plane(), outer_loop_curves=curves)
    assert _validate_face_local(f) == []


# ---------------------------------------------------------------------------
# Reject deliberately-misoriented faces
# ---------------------------------------------------------------------------


def test_cw_outer_loop_detected_by_face_validator():
    """A face built by hand with a CW outer loop must be rejected."""
    plane = _flat_plane()
    v00 = Vertex(np.array([0.0, 0.0, 0.0]))
    v10 = Vertex(np.array([1.0, 0.0, 0.0]))
    v11 = Vertex(np.array([1.0, 1.0, 0.0]))
    v01 = Vertex(np.array([0.0, 1.0, 0.0]))
    e_bot = Edge(Line3(v00.point, v10.point), 0.0, 1.0, v00, v10)
    e_rgt = Edge(Line3(v10.point, v11.point), 0.0, 1.0, v10, v11)
    e_top = Edge(Line3(v11.point, v01.point), 0.0, 1.0, v11, v01)
    e_lft = Edge(Line3(v01.point, v00.point), 0.0, 1.0, v01, v00)
    # CW traversal: v00 -> v01 -> v11 -> v10 -> v00 (i.e. each edge
    # traversed in its natural direction but in the reversed ring)
    loop = Loop(
        [
            Coedge(e_lft, False),  # v01 -> v00 reversed = v00 -> v01
            Coedge(e_top, False),  # v11 -> v01 reversed = v01 -> v11
            Coedge(e_rgt, False),  # v10 -> v11 reversed = v11 -> v10
            Coedge(e_bot, False),  # v00 -> v10 reversed = v10 -> v00
        ],
        is_outer=True,
    )
    face = Face(plane, [loop], orientation=True)
    errs = _validate_face_local(face)
    assert any("CW" in e for e in errs)


def test_cw_outer_loop_breaks_validate_body_in_closed_shell():
    """Stronger gate: a CW outer face in an otherwise-clean cube must be
    detected by the public ``validate_body`` (not just the face-local
    helper)."""
    body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
    assert validate_body(body)["ok"]
    # Flip the first face's outer loop orientation -> CW
    f0 = body.all_faces()[0]
    outer = f0.outer_loop()
    outer.coedges = [
        Coedge(c.edge, not c.orientation) for c in reversed(outer.coedges)
    ]
    outer._relink()
    res = validate_body(body)
    assert not res["ok"]
    assert any("CW" in e for e in res["errors"])


# ---------------------------------------------------------------------------
# box_to_body
# ---------------------------------------------------------------------------


def test_box_to_body_topology_counts():
    body = box_to_body((0.0, 0.0, 0.0), 2.0, 3.0, 5.0)
    c = body.euler_counts()
    assert c["V"] == 8
    assert c["E"] == 12
    assert c["F"] == 6
    assert c["S"] == 1
    assert c["G"] == 0


def test_box_to_body_validates_clean():
    body = box_to_body((0.0, 0.0, 0.0), 2.0, 3.0, 5.0)
    res = validate_body(body)
    assert res["ok"], res


def _planar_face_polygon(face: Face) -> tuple:
    """Return (vertices, centroid, outward_normal_unit) for a planar face
    whose outer loop is a polygon. Inner loops are subtracted via signed
    area / centroid (not used in this suite).
    """
    pts = []
    for ce in face.outer_loop().coedges:
        p = np.asarray(ce.start_point(), dtype=float)
        if not pts or float(np.linalg.norm(p - pts[-1])) > 1e-12:
            pts.append(p)
    n = face.surface_normal()
    return pts, n


def _divergence_volume_planar(body: Body) -> float:
    """Closed-form volume of a B-rep body whose faces are *all planar*.

    For a planar face F with outward unit normal ``n``, vertex centroid
    ``c``, and signed polygon area ``A`` (computed by half the magnitude
    of sum of (p_i x p_{i+1}) projected on ``n``), the divergence-theorem
    flux of ``F(x,y,z) = (x,y,z)/3`` through F is ``(1/3) (c . n) A``.

    The total over all faces equals the enclosed volume exactly (no
    numerical quadrature error).
    """
    total = 0.0
    for f in body.all_faces():
        pts, n = _planar_face_polygon(f)
        if len(pts) < 3:
            continue
        # signed polygon area projected on n: half-sum of cross products
        cross_sum = np.zeros(3)
        for i in range(len(pts)):
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            cross_sum += np.cross(a, b)
        signed_area = 0.5 * float(np.dot(cross_sum, n))
        # centroid of polygon (uniform-vertex approximation)
        centroid = np.mean(pts, axis=0)
        total += float(np.dot(centroid, n)) * signed_area / 3.0
    return total


def test_box_to_body_volume_matches_extents():
    body = box_to_body((0.0, 0.0, 0.0), 2.0, 3.0, 5.0)
    vol = _divergence_volume_planar(body)
    assert vol == pytest.approx(30.0, abs=1e-9)


def test_box_to_body_volume_nonzero_corner():
    body = box_to_body((1.5, -2.0, 0.25), 1.0, 4.0, 0.5)
    vol = _divergence_volume_planar(body)
    assert vol == pytest.approx(2.0, abs=1e-9)


def test_box_to_body_is_closed_shell():
    body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
    shells = body.all_shells()
    assert len(shells) == 1
    assert shells[0].is_closed is True


def test_box_to_body_each_edge_used_twice():
    """2-manifold gate: every edge appears in exactly 2 coedges."""
    body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
    for e in body.all_edges():
        live = [ce for ce in e.coedges if ce.loop is not None]
        assert len(live) == 2
        assert live[0].orientation != live[1].orientation


# ---------------------------------------------------------------------------
# cylinder_to_body
# ---------------------------------------------------------------------------


def test_cylinder_to_body_validates_clean():
    body = cylinder_to_body((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0, 2.0)
    res = validate_body(body)
    assert res["ok"], res


def test_cylinder_to_body_seam_pattern():
    """Seam topology matching :func:`brep.make_cylinder`: V=2, E=3, F=3,
    L=3 (one outer loop per face), S=1, G=0. The lateral face's single
    outer loop walks the bottom rim, the seam forward, the top rim
    reversed, then the seam reversed -- so the seam is shared by exactly
    2 coedges of opposite orientation."""
    body = cylinder_to_body((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0, 2.0)
    c = body.euler_counts()
    assert c["V"] == 2
    assert c["E"] == 3
    assert c["F"] == 3
    assert c["L"] == 3
    assert c["S"] == 1
    assert c["G"] == 0


def test_cylinder_to_body_closed_shell():
    body = cylinder_to_body((1.0, 2.0, 3.0), (1.0, 0.0, 0.0), 0.5, 4.0)
    shells = body.all_shells()
    assert len(shells) == 1
    assert shells[0].is_closed is True


def test_cylinder_to_body_handles_tilted_axis():
    body = cylinder_to_body(
        (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), radius=0.7, height=1.5,
    )
    assert validate_body(body)["ok"]


# ---------------------------------------------------------------------------
# sphere_to_body
# ---------------------------------------------------------------------------


def test_sphere_to_body_validates_clean():
    body = sphere_to_body((0.0, 0.0, 0.0), 1.0)
    res = validate_body(body)
    assert res["ok"], res


def test_sphere_to_body_is_two_manifold_closed():
    body = sphere_to_body((0.0, 0.0, 0.0), 2.5)
    shells = body.all_shells()
    assert len(shells) == 1
    assert shells[0].is_closed is True
    # the lone seam edge is used by both forward + reverse coedges
    for e in body.all_edges():
        live = [ce for ce in e.coedges if ce.loop is not None]
        assert len(live) == 2
        assert live[0].orientation != live[1].orientation


def test_sphere_to_body_genus_zero():
    body = sphere_to_body((0.0, 0.0, 0.0), 1.0)
    assert body.genus() == 0


# ---------------------------------------------------------------------------
# surfaces_to_shell sewing
# ---------------------------------------------------------------------------


def test_surfaces_to_shell_L_merges_one_edge_two_vertices():
    """Two coplanar-edged faces meeting at a common edge:
    face A: x in [0,1], y in [0,1], z = 0;
    face B: x in [0,1], y = 1, z in [0,1].

    Before sewing: 8 vertices, 8 edges. After sewing: 6 vertices, 7 edges.
    """
    plane_a = Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    plane_b = Plane(
        origin=np.array([0.0, 1.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 0.0, 1.0]),
    )
    fa = surface_to_face(plane_a)
    fb = surface_to_face(plane_b)
    shell = surfaces_to_shell([fa, fb])
    assert len(shell.vertices()) == 6
    assert len(shell.edges()) == 7
    assert shell.is_closed is False  # open L sheet


def test_surfaces_to_shell_disjoint_faces_no_merge():
    """Two faces sharing no vertices/edges -> 8 vertices, 8 edges retained."""
    plane_a = Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    plane_b = Plane(
        origin=np.array([10.0, 10.0, 10.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    fa = surface_to_face(plane_a)
    fb = surface_to_face(plane_b)
    shell = surfaces_to_shell([fa, fb])
    assert len(shell.vertices()) == 8
    assert len(shell.edges()) == 8
    assert shell.is_closed is False


def test_surfaces_to_shell_single_face_open():
    fa = surface_to_face(_flat_plane())
    shell = surfaces_to_shell([fa])
    assert len(shell.faces) == 1
    assert shell.is_closed is False


def test_surfaces_to_shell_validates_open_shell():
    """Open L shell must pass per-face structural validation."""
    plane_a = Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    plane_b = Plane(
        origin=np.array([0.0, 1.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 0.0, 1.0]),
    )
    shell = surfaces_to_shell([surface_to_face(plane_a),
                               surface_to_face(plane_b)])
    for f in shell.faces:
        assert _validate_face_local(f) == []


def test_surfaces_to_shell_rejects_empty():
    with pytest.raises(BuildError):
        surfaces_to_shell([])


# ---------------------------------------------------------------------------
# closed_shell_to_solid
# ---------------------------------------------------------------------------


def test_closed_shell_to_solid_from_box_shell():
    body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)
    shell = body.all_shells()[0]
    solid = closed_shell_to_solid(shell)
    assert isinstance(solid, Solid)
    assert solid.outer_shell is shell


def test_closed_shell_to_solid_rejects_open_shell():
    plane_a = Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    fa = surface_to_face(plane_a)
    open_shell = surfaces_to_shell([fa])
    with pytest.raises(BuildError):
        closed_shell_to_solid(open_shell)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def _structural_signature(body: Body) -> tuple:
    """A hashable structural fingerprint independent of object ids."""
    c = body.euler_counts()
    pts = sorted(
        tuple(round(x, 12) for x in v.point.tolist())
        for v in body.all_vertices()
    )
    edge_lengths = sorted(round(e.length(), 12) for e in body.all_edges())
    return (
        c["V"], c["E"], c["F"], c["L"], c["S"], c["G"],
        tuple(pts), tuple(edge_lengths),
    )


def test_box_to_body_deterministic_across_5_runs():
    sigs = {_structural_signature(box_to_body((0., 0., 0.), 2., 3., 5.))
            for _ in range(5)}
    assert len(sigs) == 1


def test_cylinder_to_body_deterministic_across_5_runs():
    sigs = {
        _structural_signature(
            cylinder_to_body((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0, 2.0)
        )
        for _ in range(5)
    }
    assert len(sigs) == 1


def test_sphere_to_body_deterministic_across_5_runs():
    sigs = {
        _structural_signature(sphere_to_body((0.0, 0.0, 0.0), 1.0))
        for _ in range(5)
    }
    assert len(sigs) == 1


# ---------------------------------------------------------------------------
# Cross-checks with brep.make_* (the synthetic-test path) -- ensure the
# production path produces equivalent topology counts to the demos
# ---------------------------------------------------------------------------


def test_box_to_body_counts_match_make_box_demo():
    from kerf_cad_core.geom.brep import make_box

    a = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0).euler_counts()
    b = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0)).euler_counts()
    for k in ("V", "E", "F", "L", "S", "G"):
        assert a[k] == b[k]


def test_cylinder_to_body_counts_match_make_cylinder_demo():
    from kerf_cad_core.geom.brep import make_cylinder

    a = cylinder_to_body((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 1.0,
                         2.0).euler_counts()
    b = make_cylinder(radius=1.0, height=2.0).euler_counts()
    for k in ("V", "E", "F", "L", "S", "G"):
        assert a[k] == b[k]


def test_sphere_to_body_counts_match_make_sphere_demo():
    from kerf_cad_core.geom.brep import make_sphere

    a = sphere_to_body((0.0, 0.0, 0.0), 1.0).euler_counts()
    b = make_sphere(radius=1.0).euler_counts()
    for k in ("V", "E", "F", "L", "S", "G"):
        assert a[k] == b[k]


# ---------------------------------------------------------------------------
# Re-export check: the additive geom.__init__ wiring must expose the new
# public surface so consumers can ``from kerf_cad_core.geom import
# box_to_body`` directly.
# ---------------------------------------------------------------------------


def test_geom_package_reexports_new_builders():
    from kerf_cad_core import geom as g

    for name in (
        "BuildError",
        "surface_to_face",
        "surfaces_to_shell",
        "closed_shell_to_solid",
        "box_to_body",
        "cylinder_to_body",
        "sphere_to_body",
    ):
        assert hasattr(g, name), f"geom package is missing re-export {name}"


# ---------------------------------------------------------------------------
# Tolerance monotonicity gate
# ---------------------------------------------------------------------------


def test_box_to_body_tolerance_monotonicity():
    """vertex.tol >= edge.tol >= face.tol on every incident triple."""
    body = box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0, tol=1e-6)
    for f in body.all_faces():
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                assert e.tol >= f.tol - 1e-15
                for v in (e.v_start, e.v_end):
                    assert v.tol >= e.tol - 1e-15


def test_surfaces_to_shell_bumps_edge_tol_to_sew_tol():
    """Sewing must bump edge tolerances so cross-face seams pass the
    loop-closure gap check inside ``validate_body``."""
    plane_a = Plane(
        origin=np.array([0.0, 0.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    plane_b = Plane(
        origin=np.array([0.0, 1.0, 0.0]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 0.0, 1.0]),
    )
    fa = surface_to_face(plane_a, tol=1e-9)
    fb = surface_to_face(plane_b, tol=1e-9)
    shell = surfaces_to_shell([fa, fb], sew_tol=1e-5)
    for e in shell.edges():
        assert e.tol >= 1e-5 - 1e-18


# ---------------------------------------------------------------------------
# BuildError carries the validate_body payload
# ---------------------------------------------------------------------------


def test_build_error_carries_payload():
    try:
        # tip: a Plane has 4 vertices/edges (V-E+F = 1, but Euler residual
        # of a one-face sheet is -1). closed_shell_to_solid on an open
        # shell raises BuildError with payload.
        plane_a = _flat_plane()
        fa = surface_to_face(plane_a)
        open_shell = surfaces_to_shell([fa])
        closed_shell_to_solid(open_shell)
    except BuildError as exc:
        assert isinstance(exc.payload, dict)
        assert exc.payload["ok"] is False
        assert exc.payload["errors"]
    else:
        pytest.fail("expected BuildError")


# ---------------------------------------------------------------------------
# Validate that real geometry (not synthetic demos) is now guarded
# ---------------------------------------------------------------------------


def test_box_to_body_corner_points_match_inputs():
    """The geometric corners returned by ``box_to_body`` must equal the
    caller-supplied (corner, extents) triple -- this is the load-bearing
    'we wrap REAL geometry' assertion."""
    body = box_to_body((1.5, -2.0, 0.25), 1.0, 4.0, 0.5)
    expected = {
        (1.5, -2.0, 0.25),
        (2.5, -2.0, 0.25),
        (2.5, 2.0, 0.25),
        (1.5, 2.0, 0.25),
        (1.5, -2.0, 0.75),
        (2.5, -2.0, 0.75),
        (2.5, 2.0, 0.75),
        (1.5, 2.0, 0.75),
    }
    actual = {
        tuple(round(c, 12) for c in v.point.tolist())
        for v in body.all_vertices()
    }
    assert actual == expected


def test_cylinder_to_body_seam_endpoints_match_geometry():
    """For axis = +z, the seam reference axis chosen by the builder is
    +y (see ``_perp(axis)`` in ``brep_build``); the seam endpoints are
    therefore at ``radius*y_axis`` at z=0 and z=h respectively. This
    asserts the production builder is wrapping REAL geometry."""
    body = cylinder_to_body((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), 2.0, 3.0)
    vs = body.all_vertices()
    assert len(vs) == 2
    pts = sorted(tuple(round(c, 12) for c in v.point.tolist()) for v in vs)
    assert pts == [(0.0, 2.0, 0.0), (0.0, 2.0, 3.0)]
    # And both must lie on the cylinder of radius 2 centred on the z-axis
    for p in pts:
        r = math.hypot(p[0], p[1])
        assert r == pytest.approx(2.0, abs=1e-12)


def test_sphere_to_body_pole_vertices_match_geometry():
    body = sphere_to_body((0.0, 0.0, 0.0), 4.0)
    pts = sorted(
        tuple(round(c, 12) for c in v.point.tolist())
        for v in body.all_vertices()
    )
    assert pts == [(0.0, 0.0, -4.0), (0.0, 0.0, 4.0)]
