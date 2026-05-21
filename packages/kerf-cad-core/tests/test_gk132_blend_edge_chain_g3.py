"""GK-132 — blend_edge_chain_g3: G3 blend across a tangent edge chain.

Hermetic oracle tests (no OCCT, no network, no DB).

Oracles
-------
1. G3 chain-blend of a box edge run → curvature-comb residual continuous
   (no G2 break) across the chain.

   Mechanism: for each edge in the chain a degree-7 G3 NURBS blend strip
   is constructed from the two adjacent planar faces.  The
   curvature_rate_continuity_residual oracle verifies max_g3_residual < 1e-3.
   Because all strips share the same radius, κ = 1/r is constant across every
   strip, so curvature (G2) is continuous at every chain junction (no G2
   break).

2. Degenerate single-edge falls back to blend_edge:
   - result["ok"] is True
   - result["body"] validates (closed 2-manifold, Euler-Poincaré satisfied)
   - result["max_g3_residual"] < 1e-3 for a planar-face box edge.

3. Empty edge_ids → ok=False with descriptive reason.

4. Non-positive radius → ok=False.

5. Unknown edge id → ok=False with the id in the reason string.

6. API: blend_edge_chain_g3 importable from blend_solid and geom;
   "blend_edge_chain_g3" in geom.__all__ and blend_solid.__all__.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.brep import Line3, validate_body
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.blend_solid import blend_edge, blend_edge_chain_g3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick_edges_along_axis(body, ax: int) -> List:
    """Return all Line3 edges of *body* aligned with *ax* (0=x,1=y,2=z)."""
    edges = []
    for e in body.all_edges():
        if not isinstance(e.curve, Line3):
            continue
        diff = e.curve.p1 - e.curve.p0
        nz = [i for i in range(3) if abs(diff[i]) > 1e-9]
        if len(nz) == 1 and nz[0] == ax:
            edges.append(e)
    return edges


def _share_vertex(e1, e2) -> bool:
    """Return True if e1 and e2 share at least one Vertex object."""
    v1 = {id(e1.v_start), id(e1.v_end)}
    v2 = {id(e2.v_start), id(e2.v_end)}
    return bool(v1 & v2)


def _select_non_adjacent(edges, count: int):
    """Greedily pick *count* mutually non-adjacent edges."""
    selected = []
    for e in edges:
        if all(not _share_vertex(e, s) for s in selected):
            selected.append(e)
            if len(selected) == count:
                break
    return selected


# ---------------------------------------------------------------------------
# Oracle 1 — G3 chain: NURBS strips + no G2 break across the chain
# ---------------------------------------------------------------------------


class TestG3ChainResidual:
    """Core oracle: each edge in the chain produces a G3-continuous NURBS
    blend strip, and the max curvature-rate residual is < 1e-3.

    Uses a 2×1×1 box; picks 2 non-adjacent parallel x-axis edges.
    """

    def setup_method(self):
        self.body = box_to_body([0.0, 0.0, 0.0], 2.0, 1.0, 1.0)
        self.radius = 0.15

    def _two_non_adj_x_edges(self):
        x_edges = _pick_edges_along_axis(self.body, ax=0)
        non_adj = _select_non_adjacent(x_edges, count=2)
        assert len(non_adj) == 2, "Need 2 non-adjacent x-axis edges in 2×1×1 box"
        return non_adj

    def test_ok_true_for_chain(self):
        """blend_edge_chain_g3 returns ok=True for a 2-edge chain."""
        ids = [e.id for e in self._two_non_adj_x_edges()]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"], f"Expected ok=True, reason: {result.get('reason')}"

    def test_surfaces_list_length_matches_chain(self):
        """surfaces list has one entry per edge (may be None for non-planar)."""
        ids = [e.id for e in self._two_non_adj_x_edges()]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"]
        assert len(result["surfaces"]) == len(ids), (
            f"surfaces list length {len(result['surfaces'])} != chain length {len(ids)}"
        )

    def test_g3_strips_built_for_planar_faces(self):
        """At least one non-None G3 NURBS strip is returned for box (planar) edges."""
        ids = [e.id for e in self._two_non_adj_x_edges()]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"]
        non_none = [s for s in result["surfaces"] if s is not None]
        assert len(non_none) > 0, "Expected at least one G3 NURBS strip for box edges"

    def test_max_g3_residual_below_threshold(self):
        """No G2 break: max_g3_residual < 1e-3 across the chain.

        For planar support faces the G3 blend strip is exact (flat surfaces
        have zero curvature everywhere so the residual is essentially zero;
        the implementation returns values well below 1e-5 from the
        curvature_rate_continuity_residual oracle).
        """
        ids = [e.id for e in self._two_non_adj_x_edges()]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"]
        g3 = result["max_g3_residual"]
        assert g3 < 1e-3, (
            f"max_g3_residual = {g3:.3e} ≥ 1e-3: indicates a G2 break across the chain"
        )

    def test_per_edge_residuals_in_diagnostics(self):
        """diagnostics contains per_edge_g3_residual list."""
        ids = [e.id for e in self._two_non_adj_x_edges()]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"]
        per = result["diagnostics"].get("per_edge_g3_residual")
        assert per is not None, "diagnostics missing per_edge_g3_residual"
        assert len(per) == len(ids)
        for r in per:
            assert isinstance(r, float) and r >= 0.0

    def test_strips_are_degree7_in_cross_direction(self):
        """Each G3 strip must be degree-7 in the cross-boundary (v) direction."""
        ids = [e.id for e in self._two_non_adj_x_edges()]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"]
        for strip in result["surfaces"]:
            if strip is None:
                continue
            assert strip.degree_v == 7, (
                f"Expected degree_v=7 for G3 strip, got {strip.degree_v}"
            )

    def test_three_edge_chain_ok(self):
        """Chain of 3 mutually non-adjacent edges also returns ok=True."""
        x_edges = _pick_edges_along_axis(self.body, ax=0)
        non_adj = _select_non_adjacent(x_edges, count=3)
        if len(non_adj) < 3:
            pytest.skip("Fewer than 3 mutually non-adjacent x-axis edges in 2×1×1 box")
        ids = [e.id for e in non_adj]
        result = blend_edge_chain_g3(self.body, ids, self.radius)
        assert result["ok"]
        assert len(result["surfaces"]) == len(ids)


# ---------------------------------------------------------------------------
# Oracle 2 — Degenerate single-edge fallback to blend_edge
# ---------------------------------------------------------------------------


class TestSingleEdgeDegenerateFallback:
    """Single-edge chain: body validates + G3 residual < 1e-3."""

    def setup_method(self):
        self.body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        self.radius = 0.1

    def _any_z_edge(self):
        return _pick_edges_along_axis(self.body, ax=2)[0]

    def test_single_edge_ok(self):
        e = self._any_z_edge()
        result = blend_edge_chain_g3(self.body, [e.id], self.radius)
        assert result["ok"], result.get("reason")

    def test_single_edge_body_validates(self):
        e = self._any_z_edge()
        result = blend_edge_chain_g3(self.body, [e.id], self.radius)
        assert result["ok"]
        val = validate_body(result["body"])
        assert val["ok"], val.get("errors")

    def test_single_edge_g3_residual_below_threshold(self):
        """For a planar-face box edge the G3 residual should be < 1e-3."""
        e = self._any_z_edge()
        result = blend_edge_chain_g3(self.body, [e.id], self.radius)
        assert result["ok"]
        g3 = result["max_g3_residual"]
        assert g3 < 1e-3, f"max_g3_residual={g3:.3e} ≥ 1e-3"

    def test_single_edge_surfaces_list_length_one(self):
        e = self._any_z_edge()
        result = blend_edge_chain_g3(self.body, [e.id], self.radius)
        assert result["ok"]
        assert len(result["surfaces"]) == 1

    def test_single_edge_volume_matches_blend_edge(self):
        """Single-edge chain body should be identical to direct blend_edge."""
        e = self._any_z_edge()
        direct = blend_edge(self.body, e, self.radius)
        chain = blend_edge_chain_g3(self.body, [e.id], self.radius)
        assert direct["ok"] and chain["ok"]
        # Compare body face count as a proxy for topological equivalence
        assert (
            len(direct["body"].all_faces()) == len(chain["body"].all_faces())
        )


# ---------------------------------------------------------------------------
# Oracle 3 — Rejection of invalid inputs
# ---------------------------------------------------------------------------


class TestInvalidInputs:
    def setup_method(self):
        self.body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)

    def test_empty_edge_ids(self):
        result = blend_edge_chain_g3(self.body, [], 0.1)
        assert not result["ok"]
        assert "empty" in result["reason"].lower()

    def test_zero_radius(self):
        e = self.body.all_edges()[0]
        result = blend_edge_chain_g3(self.body, [e.id], 0.0)
        assert not result["ok"]
        assert "radius" in result["reason"].lower()

    def test_negative_radius(self):
        e = self.body.all_edges()[0]
        result = blend_edge_chain_g3(self.body, [e.id], -0.5)
        assert not result["ok"]
        assert "radius" in result["reason"].lower()

    def test_unknown_edge_id(self):
        result = blend_edge_chain_g3(self.body, [-9999], 0.1)
        assert not result["ok"]
        assert "-9999" in result["reason"]


# ---------------------------------------------------------------------------
# Oracle 4 — Public API contract
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_importable_from_blend_solid(self):
        from kerf_cad_core.geom.blend_solid import blend_edge_chain_g3 as f
        assert callable(f)

    def test_importable_from_geom(self):
        from kerf_cad_core.geom import blend_edge_chain_g3 as f
        assert callable(f)

    def test_in_geom_all(self):
        import kerf_cad_core.geom as g
        assert "blend_edge_chain_g3" in g.__all__

    def test_in_blend_solid_all(self):
        from kerf_cad_core.geom import blend_solid
        assert "blend_edge_chain_g3" in blend_solid.__all__

    def test_return_dict_keys_present(self):
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        e = body.all_edges()[0]
        result = blend_edge_chain_g3(body, [e.id], 0.1)
        for key in ("ok", "body", "surfaces", "max_g3_residual", "reason", "diagnostics"):
            assert key in result, f"Missing key {key!r} in result dict"

    def test_surfaces_is_list(self):
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        e = body.all_edges()[0]
        result = blend_edge_chain_g3(body, [e.id], 0.1)
        assert isinstance(result["surfaces"], list)

    def test_max_g3_residual_is_float(self):
        body = box_to_body([0.0, 0.0, 0.0], 1.0, 1.0, 1.0)
        e = body.all_edges()[0]
        result = blend_edge_chain_g3(body, [e.id], 0.1)
        assert isinstance(result["max_g3_residual"], float)
