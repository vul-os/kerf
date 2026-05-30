"""
test_continuity_recovery.py
============================
Hermetic pytest oracles for continuity_recovery.py — post-Boolean G1/G2
continuity restoration at NURBS face seams.

Four analytic oracles
---------------------
1. Already-G1 seam: two coplanar NurbsSurface faces sharing a flat seam
   → recover_continuity_at_seam reports achieved_continuity='G1' and does
   NOT insert a blend (was_repaired=False, blend_surface=None).

2. G0-to-G1: two flat squares meeting at a sharp 90° corner
   → recover_continuity_at_seam(target='G1') inserts a blend strip of width
   0.05; achieved_continuity='G1'; tangent residual < 5° at midpoint.

3. G0-to-G2: same 90° setup with target='G2'
   → blend has C2-grade curvature continuity; second-derivative residual at
   blend midpoint < 0.5 (unit-normalised).

4. Body-wide pass: a two-face body (G0 sharp seam) → recover_continuity_body
   reports total_seams_fixed > 0 and per-edge achieved_continuity >= 'G1'.

All tests are pure-Python: no OCC, no database, no network.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.brep import (
    Body, Shell, Solid, Face, Loop, Coedge, Edge, Vertex, Line3,
)
from kerf_cad_core.geom.continuity_recovery import (
    ContinuityRecoveryResult,
    recover_continuity_at_seam,
    recover_continuity_body,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    """Clamped uniform knot vector for n control points at degree deg."""
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _flat_nurbs(origin, x_axis, y_axis, nx=4, ny=4, deg=1) -> NurbsSurface:
    """Flat NurbsSurface spanning origin + [0,1]*x + [0,1]*y."""
    origin = np.asarray(origin, dtype=float)
    x_axis = np.asarray(x_axis, dtype=float)
    y_axis = np.asarray(y_axis, dtype=float)
    cp = np.zeros((nx, ny, 3))
    for i in range(nx):
        for j in range(ny):
            cp[i, j] = origin + (i / (nx - 1)) * x_axis + (j / (ny - 1)) * y_axis
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nx, deg),
        knots_v=_make_knots(ny, deg),
    )


def _two_face_body(
    surf_a: NurbsSurface,
    surf_b: NurbsSurface,
    shared_verts: list,
    verts_a: list,
    verts_b: list,
) -> tuple:
    """Build a minimal 2-face open shell with one shared edge.

    Returns (body, shared_edge, face_a, face_b).
    Layout:
        va1 --- va0
         |        |
        vs0 --- vs1     <- shared edge
         |        |
        vb0 --- vb1
    """
    vs0, vs1 = shared_verts
    va0, va1 = verts_a
    vb0, vb1 = verts_b

    shared_edge = Edge(Line3(vs0.point, vs1.point), 0.0, 1.0, vs0, vs1)
    ea_top = Edge(Line3(va0.point, va1.point), 0.0, 1.0, va0, va1)
    ea_left = Edge(Line3(va1.point, vs0.point), 0.0, 1.0, va1, vs0)
    ea_right = Edge(Line3(vs1.point, va0.point), 0.0, 1.0, vs1, va0)

    eb_bot = Edge(Line3(vb0.point, vb1.point), 0.0, 1.0, vb0, vb1)
    eb_left = Edge(Line3(vs0.point, vb0.point), 0.0, 1.0, vs0, vb0)
    eb_right = Edge(Line3(vb1.point, vs1.point), 0.0, 1.0, vb1, vs1)

    loop_a = Loop(
        [
            Coedge(ea_top, True),
            Coedge(ea_left, True),
            Coedge(shared_edge, False),
            Coedge(ea_right, True),
        ],
        is_outer=True,
    )
    face_a = Face(surf_a, [loop_a], orientation=True)
    loop_a.face = face_a

    loop_b = Loop(
        [
            Coedge(shared_edge, True),
            Coedge(eb_right, False),
            Coedge(eb_bot, False),
            Coedge(eb_left, False),
        ],
        is_outer=True,
    )
    face_b = Face(surf_b, [loop_b], orientation=True)
    loop_b.face = face_b

    shell = Shell([face_a, face_b], is_closed=False)
    body = Body(shells=[shell])
    return body, shared_edge, face_a, face_b


# ---------------------------------------------------------------------------
# Fixture: G1-continuous body (two coplanar flat patches)
# ---------------------------------------------------------------------------

def _g1_seam_fixtures():
    """Two coplanar flat patches sharing a flat seam at y=0.

    Both surfaces lie in z=0.  surf_a spans y in [-1, 0], surf_b spans
    y in [0, +1].  Their shared edge is x in [0,1], y=0, z=0.
    The tangent planes are identical on both sides (both flat → G1).
    """
    surf_a = _flat_nurbs([0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    surf_b = _flat_nurbs([0.0,  0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    vs0 = Vertex(np.array([0.0, 0.0, 0.0]))
    vs1 = Vertex(np.array([1.0, 0.0, 0.0]))
    va0 = Vertex(np.array([1.0, -1.0, 0.0]))
    va1 = Vertex(np.array([0.0, -1.0, 0.0]))
    vb0 = Vertex(np.array([0.0, 1.0, 0.0]))
    vb1 = Vertex(np.array([1.0, 1.0, 0.0]))
    return _two_face_body(surf_a, surf_b, [vs0, vs1], [va0, va1], [vb0, vb1])


# ---------------------------------------------------------------------------
# Fixture: G0-only body (two flat squares meeting at 90°)
# ---------------------------------------------------------------------------

def _g0_seam_fixtures():
    """Horizontal face (z=0 plane) meets a vertical face (y=0 plane) at 90°.

    surf_a: flat horizontal x in [0,1], y in [0,1], z=0.
    surf_b: flat vertical   x in [0,1], y=0, z in [0,-1].
    Shared edge: x in [0,1], y=0, z=0.
    Normals: [0,0,1] vs [0,-1,0] — 90° apart.  Seam is G0 only.
    """
    surf_a = _flat_nurbs([0.0, 0.0,  0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    surf_b = _flat_nurbs([0.0, 0.0,  0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0])
    vs0 = Vertex(np.array([0.0, 0.0, 0.0]))
    vs1 = Vertex(np.array([1.0, 0.0, 0.0]))
    va0 = Vertex(np.array([1.0, 1.0, 0.0]))
    va1 = Vertex(np.array([0.0, 1.0, 0.0]))
    vb0 = Vertex(np.array([0.0, 0.0, -1.0]))
    vb1 = Vertex(np.array([1.0, 0.0, -1.0]))
    return _two_face_body(surf_a, surf_b, [vs0, vs1], [va0, va1], [vb0, vb1])


# ===========================================================================
# Oracle 1 — Already-G1 seam: no-op recovery
# ===========================================================================

class TestAlreadyG1Seam:
    """A coplanar seam that is already G1 must NOT be repaired."""

    def test_returns_ok(self):
        body, shared_edge, face_a, face_b = _g1_seam_fixtures()
        result = recover_continuity_at_seam(face_a, face_b, shared_edge, target="G1")
        assert result.ok is True, result.reason

    def test_no_blend_inserted(self):
        """When already G1, was_repaired must be False and blend_surface None."""
        body, shared_edge, face_a, face_b = _g1_seam_fixtures()
        result = recover_continuity_at_seam(face_a, face_b, shared_edge, target="G1")
        assert result.was_repaired is False, (
            "Coplanar seam is already G1; should not insert a blend"
        )
        assert result.blend_surface is None

    def test_achieved_continuity_g1_or_better(self):
        """Achieved continuity must be G1 or better."""
        body, shared_edge, face_a, face_b = _g1_seam_fixtures()
        result = recover_continuity_at_seam(face_a, face_b, shared_edge, target="G1")
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        assert _order.get(result.achieved_continuity, -1) >= _order["G1"], (
            f"Expected at least G1 for coplanar seam, got {result.achieved_continuity!r}"
        )

    def test_residual_zero(self):
        """No-op recovery must have residual == 0."""
        body, shared_edge, face_a, face_b = _g1_seam_fixtures()
        result = recover_continuity_at_seam(face_a, face_b, shared_edge, target="G1")
        assert result.residual == 0.0

    def test_blend_edges_empty(self):
        """No-op recovery must have empty blend_edges."""
        body, shared_edge, face_a, face_b = _g1_seam_fixtures()
        result = recover_continuity_at_seam(face_a, face_b, shared_edge, target="G1")
        assert result.blend_edges == []

    def test_result_is_continuity_recovery_result(self):
        body, shared_edge, face_a, face_b = _g1_seam_fixtures()
        result = recover_continuity_at_seam(face_a, face_b, shared_edge, target="G1")
        assert isinstance(result, ContinuityRecoveryResult)


# ===========================================================================
# Oracle 2 — G0 to G1: 90° corner gets a blend strip
# ===========================================================================

class TestG0ToG1Recovery:
    """A 90° sharp seam (G0) with target='G1' must yield a blend strip."""

    def test_returns_ok(self):
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.05
        )
        assert result.ok is True, result.reason

    def test_blend_was_inserted(self):
        """A blend strip must be inserted for a G0 seam."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.05
        )
        assert result.was_repaired is True, "G0 seam should have been repaired"
        assert result.blend_surface is not None

    def test_blend_surface_is_nurbs(self):
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.05
        )
        assert isinstance(result.blend_surface, NurbsSurface)

    def test_achieved_g1_or_better(self):
        """After G1 recovery, achieved_continuity must be G1 or better."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.05
        )
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        assert _order.get(result.achieved_continuity, -1) >= _order["G1"], (
            f"Expected G1+ after recovery, got {result.achieved_continuity!r}"
        )

    def test_tangent_residual_below_5deg(self):
        """Tangent residual at the blend midpoint must be < 5° for G1."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.05
        )
        assert result.residual < 5.0, (
            f"Tangent residual {result.residual:.3f}° should be < 5° for G1 blend"
        )

    def test_blend_has_two_boundary_edge_polylines(self):
        """Blend strip must expose two seam polylines."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.05
        )
        assert len(result.blend_edges) == 2
        for edge_polyline in result.blend_edges:
            assert len(edge_polyline) >= 2

    def test_blend_width_affects_strip(self):
        """A larger blend_width should still succeed and produce a NURBS surface."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G1", blend_width=0.2
        )
        assert result.ok is True
        assert result.blend_surface is not None


# ===========================================================================
# Oracle 3 — G0 to G2: blend has C2 curvature continuity
# ===========================================================================

class TestG0ToG2Recovery:
    """A 90° sharp seam with target='G2' must yield a G2-capable blend."""

    def test_returns_ok(self):
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G2", blend_width=0.05
        )
        assert result.ok is True, result.reason

    def test_blend_was_inserted(self):
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G2", blend_width=0.05
        )
        assert result.was_repaired is True
        assert result.blend_surface is not None

    def test_achieved_g1_or_better_for_g2_target(self):
        """G2 recovery must achieve at least G1 (ideally G2)."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G2", blend_width=0.05
        )
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        assert _order.get(result.achieved_continuity, -1) >= _order["G1"], (
            f"G2 target must achieve at least G1, got {result.achieved_continuity!r}"
        )

    def test_second_derivative_residual_small(self):
        """The G2 blend curvature residual should be < 0.5 (unit-normalised).

        We compute the second-order derivative contrast at the blend midpoint
        between the blend's v=0 boundary and surf_a.  For two flat NURBS
        surfaces the curvature is zero on both sides, so the residual is
        the blend strip's own second derivative at the seam, which should
        be small for a width-0.05 strip.
        """
        from kerf_cad_core.geom.nurbs import surface_derivatives

        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G2", blend_width=0.05
        )
        assert result.ok is True

        blend = result.blend_surface
        if blend is None:
            pytest.skip("No blend surface produced")

        # Evaluate second derivative at blend midpoint (u_mid, v=v_min)
        u_min = float(blend.knots_u[blend.degree_u])
        u_max = float(blend.knots_u[-blend.degree_u - 1])
        v_min = float(blend.knots_v[blend.degree_v])
        u_mid = 0.5 * (u_min + u_max)

        SKL = surface_derivatives(blend, u_mid, v_min, d=2)
        # Second cross-derivative (mixed) is the main G2 metric
        d2_norm = float(np.linalg.norm(SKL[0, 2][:3]))

        # For a blend of width 0.05 over flat surfaces the d² should be small
        assert d2_norm < 0.5, (
            f"Second-derivative residual at blend/seam {d2_norm:.4f} >= 0.5"
        )

    def test_blend_surface_degree_v_is_3(self):
        """The blend strip must be degree-3 in v for G2 capability."""
        body, shared_edge, face_a, face_b = _g0_seam_fixtures()
        result = recover_continuity_at_seam(
            face_a, face_b, shared_edge, target="G2", blend_width=0.05
        )
        if result.blend_surface is not None:
            assert result.blend_surface.degree_v == 3


# ===========================================================================
# Oracle 4 — Body-wide pass: recover_continuity_body
# ===========================================================================

class TestBodyWideContinuityRecovery:
    """recover_continuity_body on a two-face G0 body must fix the seam."""

    def test_returns_ok(self):
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        assert result["ok"] is True, result.get("reason", "")

    def test_total_seams_equals_one(self):
        """A two-face body has exactly one shared edge."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        assert result["total_seams"] == 1

    def test_seams_fixed_greater_than_zero(self):
        """At least one seam must be repaired in the G0 body."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        assert result["total_seams_fixed"] > 0, (
            "G0 body should have at least one seam repaired"
        )

    def test_per_edge_has_entry(self):
        """per_edge dict must have an entry for the shared edge."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        assert len(result["per_edge"]) >= 1

    def test_per_edge_achieved_g1_or_better(self):
        """Each repaired edge must achieve at least G1."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        for edge_id, info in result["per_edge"].items():
            if info["was_repaired"]:
                grade = info["continuity_after"]
                assert _order.get(grade, -1) >= _order["G1"], (
                    f"Edge {edge_id}: expected G1+ after repair, got {grade!r}"
                )

    def test_per_edge_has_blend_surface(self):
        """Repaired edges must have a blend_surface set."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        for edge_id, info in result["per_edge"].items():
            if info["was_repaired"]:
                assert info["blend_surface"] is not None, (
                    f"Edge {edge_id} was_repaired=True but no blend_surface"
                )

    def test_g1_body_has_no_seams_fixed(self):
        """A body that is already G1 should have total_seams_fixed == 0."""
        body, _, _, _ = _g1_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        assert result["ok"] is True
        assert result["total_seams_fixed"] == 0, (
            f"G1 body should need no repairs, got {result['total_seams_fixed']}"
        )

    def test_auto_fix_false_no_repairs(self):
        """With auto_fix=False, no blends should be inserted."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1", auto_fix=False)
        assert result["ok"] is True
        for edge_id, info in result["per_edge"].items():
            assert info["was_repaired"] is False

    def test_total_counts_consistent(self):
        """total_seams_fixed + total_seams_ok + total_seams_failed == total_seams."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G1")
        total = (
            result["total_seams_fixed"]
            + result["total_seams_ok"]
            + result["total_seams_failed"]
        )
        assert total == result["total_seams"]

    def test_invalid_target_returns_error(self):
        """Invalid target string must return ok=False."""
        body, _, _, _ = _g0_seam_fixtures()
        result = recover_continuity_body(body, target="G4")
        assert result["ok"] is False

    def test_importable_from_geom(self):
        """continuity_recovery must be importable from the geom package."""
        from kerf_cad_core.geom.continuity_recovery import (
            recover_continuity_at_seam as rcas,
            recover_continuity_body as rcb,
            ContinuityRecoveryResult as CRR,
        )
        assert callable(rcas)
        assert callable(rcb)
        assert CRR is not None
