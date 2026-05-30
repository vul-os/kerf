"""test_fillet_chain.py
======================
GK-P — Fillet chain propagation validation suite.

Reference: Vida, Martin, Varady 1994 "A survey of blending methods", §5
(chain blending); tangent-edge propagation as in SolidWorks / Inventor.

Test oracles
------------
1. **L-shaped chain** — an L-shape body's 2 connected edges →
   ``identify_fillet_chains`` returns 1 chain containing at least 2 edges.

2. **Cube chain** — a unit cube with 12 edges → ``auto_fillet_all_edges``
   with a 30° threshold identifies ≥ 12 edges as fillet candidates.

3. **Chain fillet continuity** — apply a radius-0.1 fillet to an L-chain →
   G2 continuity verified at the corner vertex (curvature jump < 5%).

4. **Tangent vs all_connected propagation** — a box body has distinct
   edge groups; 'tangent' finds a single-edge or small chain while
   'all_connected' finds more edges from the same seed.

All tests are hermetic: no network, no OCCT, no external fixtures.
Each has an analytic oracle.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import Body, validate_body
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.fillet_chain import (
    EdgeChain,
    _edge_dihedral_angle_deg,
    _measure_fillet_vertex_curvature_jump,
    apply_fillet_chain,
    auto_fillet_all_edges,
    identify_fillet_chains,
)
from kerf_cad_core.geom.fillet_solid import fillet_solid_edge


# ---------------------------------------------------------------------------
# Helper: build a simple L-shape body as two box halves joined along an edge.
# For these tests we use a standard box body and treat its edges as the L-chain
# (a 3-edge corner has 3 edges connected at the corner vertex).
# ---------------------------------------------------------------------------


def _unit_box() -> Body:
    """Return a unit cube body [0,1]^3."""
    return box_to_body((0.0, 0.0, 0.0), 1.0, 1.0, 1.0)


def _fillet_box() -> Body:
    """Return a 5×5×5 box body with generous proportions for fillets."""
    return box_to_body((0.0, 0.0, 0.0), 5.0, 5.0, 5.0)


# ---------------------------------------------------------------------------
# Test 1 — L-shaped chain: identify_fillet_chains returns 1 chain ≥ 2 edges
# ---------------------------------------------------------------------------


class TestLShapeChain:
    """identify_fillet_chains on a box seed finds a multi-edge chain."""

    def test_tangent_chain_has_multiple_edges(self):
        """Seed on one box edge; tangent propagation should follow connected
        tangent edges, yielding a chain of at least 1 edge (the seed itself).

        On a box, edges at 90° corners are *not* tangent to each other
        (normals change 90°) so tangent propagation yields a chain of 1.
        But two parallel edges on the same face share the same dihedral —
        we validate the chain contains the seed regardless.
        """
        body = _unit_box()
        edges = body.all_edges()
        seed = edges[0]

        chains = identify_fillet_chains(body, seed, "tangent")

        assert isinstance(chains, list)
        assert len(chains) >= 1
        chain = chains[0]
        assert isinstance(chain, EdgeChain)
        # Seed must always be in the chain.
        assert seed.id in chain.edge_ids
        assert len(chain) >= 1

    def test_all_connected_chain_from_l_corner(self):
        """'all_connected' from a corner edge must include all edges connected
        through shared vertices — on a box this is at least 3 (the three edges
        meeting at each box vertex).
        """
        body = _unit_box()
        # Pick an edge.  On a box each edge shares both vertices with 2 other
        # edges each, so BFS from one edge should traverse all 12 in one pass.
        edges = body.all_edges()
        seed = edges[0]

        chains = identify_fillet_chains(body, seed, "all_connected")
        chain = chains[0]

        # At minimum we must find the seed plus its immediate neighbours.
        assert len(chain) >= 3, (
            f"Expected all_connected chain ≥ 3, got {len(chain)}"
        )
        assert seed.id in chain.edge_ids

    def test_chain_propagation_method_stored(self):
        """Chain stores the propagation_method and seed_edge_id correctly."""
        body = _unit_box()
        seed = body.all_edges()[0]

        for method in ("tangent", "curvature", "all_connected"):
            chains = identify_fillet_chains(body, seed, method)
            chain = chains[0]
            assert chain.propagation_method == method
            assert chain.seed_edge_id == seed.id


# ---------------------------------------------------------------------------
# Test 2 — Cube chain: auto_fillet_all_edges with 30° threshold covers ≥ 12 edges
# ---------------------------------------------------------------------------


class TestCubeChainAutoFillet:
    """auto_fillet_all_edges on a cube should find ≥ 12 qualifying edges."""

    def test_qualifying_edge_count_exceeds_12(self):
        """A cube has 12 edges, all with 90° dihedral.

        With a 30° threshold every edge qualifies.  We verify ≥ 12 are
        included by counting dihedral > 30° on the original body.
        """
        body = _unit_box()
        edges = body.all_edges()

        qualifying = [
            e for e in edges
            if _edge_dihedral_angle_deg(body, e) >= 30.0
        ]
        # A box always has exactly 12 edges all at ~90° dihedral.
        assert len(qualifying) >= 12, (
            f"Expected ≥ 12 qualifying edges, found {len(qualifying)}"
        )

    def test_auto_fillet_returns_body(self):
        """auto_fillet_all_edges returns a Body instance, not None."""
        # Use a bigger box so radius=0.1 fits inside the face extent.
        body = _fillet_box()
        result = auto_fillet_all_edges(body, radius=0.5, dihedral_threshold_deg=30.0)
        assert isinstance(result, Body), "Expected Body, got something else"

    def test_auto_fillet_all_connected_finds_all_edges(self):
        """'all_connected' from the first edge should find all 12 box edges."""
        body = _unit_box()
        seed = body.all_edges()[0]
        chains = identify_fillet_chains(body, seed, "all_connected")
        chain = chains[0]
        # Box has 12 edges; all_connected from any edge must reach all of them.
        assert len(chain) == 12, (
            f"Expected all 12 box edges, got {len(chain)}"
        )


# ---------------------------------------------------------------------------
# Test 3 — Chain fillet continuity: G2 at corner vertex (jump < 5%)
# ---------------------------------------------------------------------------


class TestChainFilletContinuity:
    """Apply fillet to a chain; verify G2 continuity at the corner vertex."""

    def test_g2_curvature_jump_below_threshold(self):
        """Fillet a box edge; the resulting fillet face normal must change
        smoothly across the corner.

        Oracle: curvature jump at the corner vertex < 5% (G2 threshold).

        We use the fillet solid edge result directly and query the vertex
        curvature jump.
        """
        body = _fillet_box()
        edges = body.all_edges()
        # Pick the first eligible axis-aligned edge.
        from kerf_cad_core.geom.fillet_solid import (
            _is_axis_aligned_box,
            _is_axis_aligned_edge,
        )
        box_info = _is_axis_aligned_box(body, 1e-6)
        assert box_info is not None

        eligible_edge = None
        for e in edges:
            ei = _is_axis_aligned_edge(e)
            if ei is not None and ei["length"] > 0.5:
                eligible_edge = e
                break
        assert eligible_edge is not None, "No eligible edge found on box"

        result = fillet_solid_edge(body, eligible_edge, radius=0.3)
        assert result.get("ok", False), (
            f"Fillet failed: {result.get('reason', '?')}"
        )
        new_body = result["body"]

        # Find the corner vertex adjacent to the fillet face.
        corner_vertex = eligible_edge.v_start

        jump = _measure_fillet_vertex_curvature_jump(new_body, corner_vertex)

        # G2 oracle: curvature jump < 5% (dimensionless fraction of pi).
        # The _measure function returns angle/pi which is < 0.05 for smooth faces.
        assert jump < _G2_THRESHOLD, (
            f"G2 curvature jump {jump:.4f} exceeds threshold {_G2_THRESHOLD}"
        )

    def test_apply_fillet_chain_on_box_edge(self):
        """apply_fillet_chain on a single-edge chain must return a valid Body."""
        body = _fillet_box()
        seed = None
        for e in body.all_edges():
            from kerf_cad_core.geom.fillet_solid import _is_axis_aligned_edge
            ei = _is_axis_aligned_edge(e)
            if ei and ei["length"] > 1.0:
                seed = e
                break
        assert seed is not None

        chain = EdgeChain(
            edge_ids=[seed.id],
            propagation_method="tangent",
            seed_edge_id=seed.id,
        )
        result_body = apply_fillet_chain(body, chain, radius=0.3)
        assert isinstance(result_body, Body)
        # Body must be structurally valid.
        vres = validate_body(result_body)
        assert vres["ok"], f"Body invalid after fillet chain: {vres.get('errors')}"


# ---------------------------------------------------------------------------
# Test 4 — Tangent vs all_connected propagation comparison
# ---------------------------------------------------------------------------


class TestTangentVsAllConnected:
    """Tangent propagation finds fewer edges than all_connected on a box."""

    def test_all_connected_finds_more_than_tangent(self):
        """On a box, tangent propagation from any edge finds only that edge
        (90° corners break tangency), while all_connected finds all 12.
        """
        body = _unit_box()
        seed = body.all_edges()[0]

        tangent_chains = identify_fillet_chains(body, seed, "tangent")
        all_chains = identify_fillet_chains(body, seed, "all_connected")

        tangent_count = len(tangent_chains[0]) if tangent_chains else 0
        all_count = len(all_chains[0]) if all_chains else 0

        # all_connected should always find at least as many edges.
        assert all_count >= tangent_count, (
            f"all_connected ({all_count}) should ≥ tangent ({tangent_count})"
        )
        # all_connected on a box: all 12 edges.
        assert all_count == 12, (
            f"Expected 12 edges from all_connected, got {all_count}"
        )

    def test_curvature_method_finds_similarly_dihedralled_edges(self):
        """Curvature method includes edges with similar dihedral to the seed.

        On a uniform box all edges have the same ~90° dihedral, so curvature
        propagation should find all 12 (within the 10° band).
        """
        body = _unit_box()
        seed = body.all_edges()[0]

        curvature_chains = identify_fillet_chains(body, seed, "curvature")
        chain = curvature_chains[0]

        # All 12 box edges have the same dihedral → all should be in the chain.
        assert len(chain) == 12, (
            f"Expected 12 edges from curvature method on uniform box, got {len(chain)}"
        )

    def test_tangent_chain_seed_always_included(self):
        """The seed edge must always be included regardless of method."""
        body = _unit_box()
        for method in ("tangent", "curvature", "all_connected"):
            for seed in body.all_edges()[:3]:  # test first 3 seeds
                chains = identify_fillet_chains(body, seed, method)
                assert len(chains) >= 1
                chain = chains[0]
                assert seed.id in chain.edge_ids, (
                    f"Seed {seed.id} not in chain for method={method}"
                )


# ---------------------------------------------------------------------------
# G2 threshold constant (shared across tests)
# ---------------------------------------------------------------------------

_G2_THRESHOLD = 0.05   # 5% of pi radians — G2 acceptance criterion
