"""
test_gk138_continuity_audit.py
================================
Hermetic pytest oracle for GK-138 — continuity_audit.

Oracles
-------
1. A two-patch body built from NurbsSurface faces that share a G1-continuous
   seam (tangent-plane matching, as would be produced by a fillet or blend)
   reports ``'G1'`` or better across the shared fillet seam.

2. A two-patch body built from NurbsSurface faces that meet at a sharp 90°
   angle (as the edges of a box do) reports ``'G0'`` across the shared edge —
   positional continuity but no tangent continuity.

All tests are pure-Python: no OCC, no database, no network.
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.brep import (
    Body, Shell, Solid, Face, Loop, Coedge, Edge, Vertex,
    Line3,
)
from kerf_cad_core.geom.surface_analysis import continuity_audit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    """Clamped uniform knot vector for *n* control points, degree *deg*."""
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _flat_nurbs(origin, x_axis, y_axis, nx=4, ny=4, deg=1) -> NurbsSurface:
    """Build a flat NurbsSurface spanning origin + [0,1]*x_axis + [0,1]*y_axis."""
    origin = np.asarray(origin, dtype=float)
    x_axis = np.asarray(x_axis, dtype=float)
    y_axis = np.asarray(y_axis, dtype=float)
    cp = np.zeros((nx, ny, 3))
    for i in range(nx):
        for j in range(ny):
            cp[i, j] = (
                origin
                + (i / (nx - 1)) * x_axis
                + (j / (ny - 1)) * y_axis
            )
    return NurbsSurface(
        degree_u=deg,
        degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nx, deg),
        knots_v=_make_knots(ny, deg),
    )


def _two_face_body(
    surf_a: NurbsSurface,
    surf_b: NurbsSurface,
    shared_verts: list,  # 2 vertices at the shared edge endpoints
    verts_a: list,       # other 2 vertices for face A (not on shared edge)
    verts_b: list,       # other 2 vertices for face B (not on shared edge)
) -> Body:
    """Build a minimal 2-face open shell with one shared edge.

    Layout (looking from above):

        va1 --- va0
         |        |
        vs0 --- vs1     ← shared edge (vs0 → vs1)
         |        |
        vb0 --- vb1

    Face A: va0 → vs1 → vs0 → va1 (quad, CCW from outside)
    Face B: vs0 → vs1 → vb1 → vb0 (quad, CCW from outside)
    Shared edge: vs0 ↔ vs1

    Parameters
    ----------
    shared_verts : [Vertex, Vertex]   vs0, vs1
    verts_a      : [Vertex, Vertex]   va0, va1 (top two for face A)
    verts_b      : [Vertex, Vertex]   vb0, vb1 (bottom two for face B)
    """
    vs0, vs1 = shared_verts
    va0, va1 = verts_a
    vb0, vb1 = verts_b

    # Build edges (shared edge is reused)
    shared_edge = Edge(
        Line3(vs0.point, vs1.point), 0.0, 1.0, vs0, vs1
    )
    ea_top = Edge(Line3(va0.point, va1.point), 0.0, 1.0, va0, va1)
    ea_left = Edge(Line3(va1.point, vs0.point), 0.0, 1.0, va1, vs0)
    ea_right = Edge(Line3(vs1.point, va0.point), 0.0, 1.0, vs1, va0)

    eb_bot = Edge(Line3(vb0.point, vb1.point), 0.0, 1.0, vb0, vb1)
    eb_left = Edge(Line3(vs0.point, vb0.point), 0.0, 1.0, vs0, vb0)
    eb_right = Edge(Line3(vb1.point, vs1.point), 0.0, 1.0, vb1, vs1)

    # Face A: va0 → va1 → vs0 → vs1 (CCW from +z)
    # Coedge order: top (va0→va1), left (va1→vs0), shared_rev (vs0←vs1),
    #               right_rev (vs1→va0)
    loop_a = Loop(
        [
            Coedge(ea_top, True),           # va0 → va1
            Coedge(ea_left, True),          # va1 → vs0
            Coedge(shared_edge, False),     # vs1 ← vs0  (reversed use)
            Coedge(ea_right, True),         # vs1 → va0
        ],
        is_outer=True,
    )
    face_a = Face(surf_a, [loop_a], orientation=True)
    loop_a.face = face_a

    # Face B: vs0 → vs1 → vb1 → vb0 (CCW from +z)
    loop_b = Loop(
        [
            Coedge(shared_edge, True),      # vs0 → vs1 (forward use)
            Coedge(eb_right, False),        # vs1 ← vb1
            Coedge(eb_bot, False),          # vb0 ← vb1
            Coedge(eb_left, False),         # vs0 ← vb0
        ],
        is_outer=True,
    )
    face_b = Face(surf_b, [loop_b], orientation=True)
    loop_b.face = face_b

    shell = Shell([face_a, face_b], is_closed=False)
    body = Body(shells=[shell])
    return body


# ---------------------------------------------------------------------------
# Fixture 1 — fillet-sewn body: two coplanar patches → G1 (or better)
# ---------------------------------------------------------------------------

def _make_g1_body() -> Body:
    """Two NurbsSurface patches sharing a G1-continuous seam.

    Both patches lie in the same tangent plane along the shared edge
    (the seam is the line y=0; surf_A spans y in [-1,0], surf_B spans
    y in [0,+1]).  The cross-boundary tangent direction is identical on
    both sides → the seam is analytically G1 (tangent-plane continuous).

    Because both patches are flat (degree 1), curvature is zero on both
    sides → the seam is also G2 and G3.
    """
    # surf_A: flat patch spanning x∈[0,1], y∈[-1,0], z=0
    surf_a = _flat_nurbs(
        origin=[0.0, -1.0, 0.0],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 1.0, 0.0],
    )
    # surf_B: flat patch spanning x∈[0,1], y∈[0,1], z=0
    surf_b = _flat_nurbs(
        origin=[0.0, 0.0, 0.0],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 1.0, 0.0],
    )

    # Shared edge: x∈[0,1], y=0, z=0
    vs0 = Vertex(np.array([0.0, 0.0, 0.0]))
    vs1 = Vertex(np.array([1.0, 0.0, 0.0]))

    # Face A extra vertices (y=-1)
    va0 = Vertex(np.array([1.0, -1.0, 0.0]))
    va1 = Vertex(np.array([0.0, -1.0, 0.0]))

    # Face B extra vertices (y=+1)
    vb0 = Vertex(np.array([0.0, 1.0, 0.0]))
    vb1 = Vertex(np.array([1.0, 1.0, 0.0]))

    return _two_face_body(surf_a, surf_b, [vs0, vs1], [va0, va1], [vb0, vb1])


# ---------------------------------------------------------------------------
# Fixture 2 — sharp box edge: two patches at 90° → G0
# ---------------------------------------------------------------------------

def _make_g0_body() -> Body:
    """Two NurbsSurface patches sharing a sharp 90° seam.

    surf_A lies in the z=0 plane (horizontal).
    surf_B lies in the y=0 plane (vertical, perpendicular to surf_A).
    They share the edge x∈[0,1], y=0, z=0.

    At the shared edge the surface normals are [0,0,1] and [0,-1,0]
    respectively — 90° apart.  The seam is G0 (positionally continuous)
    but not G1 (tangent planes differ).
    """
    # surf_A: flat horizontal patch  x∈[0,1], y∈[0,1], z=0
    surf_a = _flat_nurbs(
        origin=[0.0, 0.0, 0.0],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 1.0, 0.0],
    )
    # surf_B: flat vertical patch  x∈[0,1], y=0, z∈[0,-1]
    surf_b = _flat_nurbs(
        origin=[0.0, 0.0, 0.0],
        x_axis=[1.0, 0.0, 0.0],
        y_axis=[0.0, 0.0, -1.0],
    )

    # Shared edge: x∈[0,1], y=0, z=0
    vs0 = Vertex(np.array([0.0, 0.0, 0.0]))
    vs1 = Vertex(np.array([1.0, 0.0, 0.0]))

    # Face A extra vertices (y=+1, z=0)
    va0 = Vertex(np.array([1.0, 1.0, 0.0]))
    va1 = Vertex(np.array([0.0, 1.0, 0.0]))

    # Face B extra vertices (y=0, z=-1)
    vb0 = Vertex(np.array([0.0, 0.0, -1.0]))
    vb1 = Vertex(np.array([1.0, 0.0, -1.0]))

    return _two_face_body(surf_a, surf_b, [vs0, vs1], [va0, va1], [vb0, vb1])


# ---------------------------------------------------------------------------
# Oracle 1 — G1 (fillet-like) body
# ---------------------------------------------------------------------------

class TestContinuityAuditG1Body:
    """A two-patch body whose shared edge is G1-continuous reports G1 or
    better for that edge."""

    def test_returns_ok(self):
        body = _make_g1_body()
        result = continuity_audit(body, tol=1e-4)
        assert result["ok"] is True, result.get("reason", "")

    def test_has_shared_edge(self):
        body = _make_g1_body()
        result = continuity_audit(body, tol=1e-4)
        assert len(result["edge_continuity"]) >= 1, (
            "Expected at least one shared edge in a two-face body"
        )

    def test_fillet_seam_is_g1_or_better(self):
        """The shared seam between two tangent-continuous flat patches must be
        reported as G1, G2, or G3 — not G0 or below."""
        body = _make_g1_body()
        result = continuity_audit(body, tol=1e-4)
        assert result["ok"] is True, result.get("reason", "")
        grades = list(result["edge_continuity"].values())
        assert len(grades) >= 1, "No shared edges found"
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        for grade in grades:
            assert _order.get(grade, -1) >= _order["G1"], (
                f"Fillet seam should be at least G1, got {grade!r}"
            )

    def test_summary_total_matches_edge_count(self):
        body = _make_g1_body()
        result = continuity_audit(body, tol=1e-4)
        ec = result["edge_continuity"]
        s = result["summary"]
        assert s["total_shared_edges"] == len(ec)

    def test_summary_counts_sum_to_total(self):
        body = _make_g1_body()
        result = continuity_audit(body, tol=1e-4)
        s = result["summary"]
        total = sum(s.get(g, 0) for g in ("G3", "G2", "G1", "G0", "below_G0"))
        assert total == s["total_shared_edges"]

    def test_worst_continuity_in_summary(self):
        body = _make_g1_body()
        result = continuity_audit(body, tol=1e-4)
        s = result["summary"]
        assert s["worst_continuity"] is not None
        assert s["worst_continuity"] in ("G3", "G2", "G1", "G0", "below_G0")

    def test_import_from_geom(self):
        """continuity_audit must be importable directly from kerf_cad_core.geom."""
        from kerf_cad_core.geom import continuity_audit as ca  # noqa: F401
        assert callable(ca)


# ---------------------------------------------------------------------------
# Oracle 2 — G0 (sharp box edge) body
# ---------------------------------------------------------------------------

class TestContinuityAuditG0Body:
    """A two-patch body whose shared edge is a sharp 90° corner reports G0
    (not G1) for that edge."""

    def test_returns_ok(self):
        body = _make_g0_body()
        result = continuity_audit(body, tol=1e-4)
        assert result["ok"] is True, result.get("reason", "")

    def test_has_shared_edge(self):
        body = _make_g0_body()
        result = continuity_audit(body, tol=1e-4)
        assert len(result["edge_continuity"]) >= 1

    def test_sharp_edge_is_g0_not_g1(self):
        """A 90° edge between perpendicular NurbsSurface patches must be
        reported as G0 (position-continuous) but NOT G1 (tangent differs)."""
        body = _make_g0_body()
        result = continuity_audit(body, tol=1e-4)
        assert result["ok"] is True, result.get("reason", "")
        grades = list(result["edge_continuity"].values())
        assert len(grades) >= 1, "No shared edges found"
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        for grade in grades:
            assert _order.get(grade, -1) <= _order["G0"], (
                f"Sharp 90° edge should be at most G0, got {grade!r}"
            )

    def test_sharp_grade_strictly_below_g1_body(self):
        """The sharp body's worst continuity is strictly lower than the G1
        body's worst continuity."""
        body_g1 = _make_g1_body()
        body_g0 = _make_g0_body()
        r_g1 = continuity_audit(body_g1, tol=1e-4)
        r_g0 = continuity_audit(body_g0, tol=1e-4)
        _order = {"below_G0": 0, "G0": 1, "G1": 2, "G2": 3, "G3": 4}
        worst_g1 = r_g1["summary"]["worst_continuity"]
        worst_g0 = r_g0["summary"]["worst_continuity"]
        assert _order[worst_g0] < _order[worst_g1], (
            f"Sharp body ({worst_g0}) should have lower continuity than "
            f"G1 body ({worst_g1})"
        )

    def test_empty_body_returns_ok_false(self):
        """An empty Body (no edges) returns ok=False with a useful reason."""
        body = Body()
        result = continuity_audit(body, tol=1e-4)
        assert result["ok"] is False
        assert result["reason"]

    def test_summary_present_for_sharp_body(self):
        body = _make_g0_body()
        result = continuity_audit(body, tol=1e-4)
        s = result["summary"]
        assert "total_shared_edges" in s
        assert "worst_continuity" in s
