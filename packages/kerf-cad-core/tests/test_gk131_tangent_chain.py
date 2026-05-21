"""GK-131 — Tangent-chain edge auto-select oracle tests.

Pure-Python, hermetic.  No OCCT, no network, no DB.

Oracles
-------
1. Rounded-box top face: seed edge on the rounded top returns all 4
   tangent-connected arc edges.
2. Sharp cube edge: seed edge on a plain box returns just the seed (all
   adjacent edges are perpendicular, not tangent-continuous).
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
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
)
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.fillet_solid import tangent_edge_chain


# ---------------------------------------------------------------------------
# Helpers — build a synthetic "rounded-box top face" body
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _make_rounded_top_body() -> tuple:
    """Construct a minimal Body whose single-face loop consists of exactly
    4 quarter-circle arcs arranged in a closed tangent-continuous chain.

    Geometry (all at z = 1, radius = 1 centred at origin):
        4 quarter arcs of the unit circle, swept CCW in the XY plane.

        Arc 0: from (0, -1, 1) to (1,  0, 1)  — t in [-π/2, 0]
        Arc 1: from (1,  0, 1) to (0,  1, 1)  — t in [0,    π/2]
        Arc 2: from (0,  1, 1) to (-1, 0, 1)  — t in [π/2,  π]
        Arc 3: from (-1, 0, 1) to (0, -1, 1)  — t in [π, 3π/2]

    At each junction vertex the departing tangent of the next arc equals
    the arriving tangent of the current arc (both point CCW along the
    circle), so the chain is exactly G1-continuous.

    Returns (body, arc_edge_ids) where arc_edge_ids is the list of the 4
    arc edge ids.
    """
    z = 1.0
    # Junction vertices at the axis-crossing points of the unit circle.
    v_b   = Vertex(np.array([0.0,  -1.0, z]))   # bottom  (0,-1,z)
    v_r   = Vertex(np.array([1.0,   0.0, z]))   # right   (1, 0,z)
    v_t   = Vertex(np.array([0.0,   1.0, z]))   # top     (0, 1,z)
    v_l   = Vertex(np.array([-1.0,  0.0, z]))   # left   (-1, 0,z)

    # All 4 arcs share the same circle: center (0,0,z), radius 1,
    # x_axis=(1,0,0), y_axis=(0,1,0).  evaluate(t)=(cos t, sin t, z).
    # The derivative is (-sin t, cos t, 0) — always tangent CCW.
    # t0→t1 for each arc:
    #   Arc 0: [-π/2, 0]   → (0,-1,z) → (1, 0,z)
    #   Arc 1: [0,    π/2] → (1, 0,z) → (0, 1,z)
    #   Arc 2: [π/2,  π]   → (0, 1,z) → (-1,0,z)
    #   Arc 3: [π, 3π/2]   → (-1,0,z) → (0,-1,z)
    ORIGIN = np.array([0.0, 0.0, z])
    X_AX   = np.array([1.0, 0.0, 0.0])
    Y_AX   = np.array([0.0, 1.0, 0.0])
    R = 1.0
    HALF_PI = math.pi / 2

    arc0 = CircleArc3(center=ORIGIN, radius=R, x_axis=X_AX, y_axis=Y_AX,
                      t0=-HALF_PI, t1=0.0)
    arc1 = CircleArc3(center=ORIGIN, radius=R, x_axis=X_AX, y_axis=Y_AX,
                      t0=0.0, t1=HALF_PI)
    arc2 = CircleArc3(center=ORIGIN, radius=R, x_axis=X_AX, y_axis=Y_AX,
                      t0=HALF_PI, t1=math.pi)
    arc3 = CircleArc3(center=ORIGIN, radius=R, x_axis=X_AX, y_axis=Y_AX,
                      t0=math.pi, t1=3 * HALF_PI)

    # Verify arc endpoints.
    assert np.allclose(arc0.evaluate(-HALF_PI), [0.0, -1.0, z], atol=1e-12)
    assert np.allclose(arc0.evaluate(0.0),      [1.0,  0.0, z], atol=1e-12)
    assert np.allclose(arc1.evaluate(0.0),      [1.0,  0.0, z], atol=1e-12)
    assert np.allclose(arc1.evaluate(HALF_PI),  [0.0,  1.0, z], atol=1e-12)
    assert np.allclose(arc2.evaluate(HALF_PI),  [0.0,  1.0, z], atol=1e-12)
    assert np.allclose(arc2.evaluate(math.pi),  [-1.0, 0.0, z], atol=1e-12)
    assert np.allclose(arc3.evaluate(math.pi),  [-1.0, 0.0, z], atol=1e-12)
    assert np.allclose(arc3.evaluate(3*HALF_PI),[0.0, -1.0, z], atol=1e-12)

    tol = 1e-7
    e0 = Edge(arc0, -HALF_PI,   0.0,         v_b, v_r, tol)
    e1 = Edge(arc1,  0.0,       HALF_PI,     v_r, v_t, tol)
    e2 = Edge(arc2,  HALF_PI,   math.pi,     v_t, v_l, tol)
    e3 = Edge(arc3,  math.pi,   3*HALF_PI,   v_l, v_b, tol)

    loop = Loop(
        [Coedge(e0, True), Coedge(e1, True), Coedge(e2, True), Coedge(e3, True)],
        is_outer=True,
    )
    plane = Plane(
        origin=np.array([0.0, 0.0, z]),
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 1.0, 0.0]),
    )
    face = Face(plane, [loop], orientation=True, tol=tol)
    shell = Shell([face], is_closed=False)
    body = Body(shells=[shell])

    arc_edge_ids = [e0.id, e1.id, e2.id, e3.id]
    return body, arc_edge_ids


# ---------------------------------------------------------------------------
# Oracle 1 — Rounded-box top face: 4 tangent arcs
# ---------------------------------------------------------------------------

class TestRoundedTopFaceChain:
    """Seed on any of the 4 arcs → chain == all 4 arcs."""

    def setup_method(self):
        self.body, self.arc_ids = _make_rounded_top_body()

    def test_seed_returns_all_four_arcs(self):
        chain = tangent_edge_chain(self.body, self.arc_ids[0], angle_tol_deg=5.0)
        assert set(chain) == set(self.arc_ids), (
            f"Expected all 4 arc ids {self.arc_ids}, got {chain}"
        )

    def test_chain_length_is_four(self):
        chain = tangent_edge_chain(self.body, self.arc_ids[0], angle_tol_deg=5.0)
        assert len(chain) == 4

    def test_seed_is_in_chain(self):
        seed = self.arc_ids[2]
        chain = tangent_edge_chain(self.body, seed, angle_tol_deg=5.0)
        assert seed in chain

    def test_all_seeds_return_same_set(self):
        """Starting from any of the 4 arcs yields the same 4-arc chain."""
        results = [
            set(tangent_edge_chain(self.body, sid, angle_tol_deg=5.0))
            for sid in self.arc_ids
        ]
        for r in results:
            assert r == set(self.arc_ids)

    def test_tight_tolerance_still_finds_chain(self):
        """Arcs are exactly tangent; even tol=0.1° should pass."""
        chain = tangent_edge_chain(self.body, self.arc_ids[0], angle_tol_deg=0.1)
        assert set(chain) == set(self.arc_ids)


# ---------------------------------------------------------------------------
# Oracle 2 — Sharp cube edge: isolated seed
# ---------------------------------------------------------------------------

class TestSharpCubeEdge:
    """On a plain box every adjacent edge is perpendicular to the seed.

    The chain must contain only the seed edge itself (no tangent neighbours).
    """

    def setup_method(self):
        self.body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)

    def _any_top_edge(self) -> Edge:
        """Return one of the 4 top edges of the unit box (at z=1)."""
        for e in self.body.all_edges():
            if isinstance(e.curve, Line3):
                z0 = float(e.v_start.point[2])
                z1 = float(e.v_end.point[2])
                if abs(z0 - 1.0) < 1e-6 and abs(z1 - 1.0) < 1e-6:
                    return e
        raise RuntimeError("No top edge found in unit box")

    def test_sharp_edge_returns_only_seed(self):
        seed = self._any_top_edge()
        chain = tangent_edge_chain(self.body, seed.id, angle_tol_deg=5.0)
        # All adjacent edges are at 90° — only the seed is in the chain.
        assert seed.id in chain
        assert len(chain) == 1, (
            f"Expected chain of length 1 for sharp box edge, got {len(chain)}: "
            f"{chain}"
        )

    def test_sharp_edge_default_tolerance(self):
        seed = self._any_top_edge()
        chain = tangent_edge_chain(self.body, seed.id)
        assert len(chain) == 1

    def test_invalid_seed_raises_key_error(self):
        with pytest.raises(KeyError):
            tangent_edge_chain(self.body, -9999, angle_tol_deg=5.0)


# ---------------------------------------------------------------------------
# Oracle 3 — API / import smoke
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_importable_from_geom(self):
        from kerf_cad_core.geom import tangent_edge_chain as f
        assert callable(f)

    def test_in_geom_all(self):
        import kerf_cad_core.geom as g
        assert "tangent_edge_chain" in g.__all__

    def test_in_fillet_solid_all(self):
        from kerf_cad_core.geom import fillet_solid
        assert "tangent_edge_chain" in fillet_solid.__all__

    def test_returns_list(self):
        body, arc_ids = _make_rounded_top_body()
        result = tangent_edge_chain(body, arc_ids[0])
        assert isinstance(result, list)
        assert all(isinstance(x, int) for x in result)
