"""
Tests for kerf_electronics.ratsnest — MST ratsnest computation.

Oracles
-------
1. MST on a known square (4 pads at corners) has the expected total length.
2. MST length is minimal compared to a non-MST (star) topology.
3. Single-net, 2-pad circuit produces exactly 1 edge.
4. Pads with no net_id are ignored.
5. compute_ratsnest groups correctly by net_id.
6. Empty circuit returns empty list.
7. Net with only 1 pad returns no edges.
"""

from __future__ import annotations

import math
import pytest

from kerf_electronics.ratsnest import compute_ratsnest, compute_net_mst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pad(pad_id: str, x: float, y: float, net_id: str = "NET1") -> dict:
    return {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": pad_id,
        "x": x,
        "y": y,
        "width": 1.0,
        "height": 1.0,
        "net_id": net_id,
    }


def _total_length(edges: list) -> float:
    return sum(e["length_mm"] for e in edges)


# ---------------------------------------------------------------------------
# compute_net_mst — low-level MST oracle tests
# ---------------------------------------------------------------------------

class TestComputeNetMST:
    """Unit tests for compute_net_mst with known inputs."""

    def test_two_pads_single_edge(self):
        """Two pads 3 mm apart → one edge with length 3."""
        pads = [
            {"x": 0.0, "y": 0.0, "pad_id": "A"},
            {"x": 3.0, "y": 0.0, "pad_id": "B"},
        ]
        edges = compute_net_mst(pads)
        assert len(edges) == 1
        assert math.isclose(edges[0]["length_mm"], 3.0, rel_tol=1e-9)

    def test_three_pads_collinear(self):
        """Three collinear pads: MST picks the two shorter edges, not the long one."""
        # Positions: 0, 1, 10
        pads = [
            {"x": 0.0, "y": 0.0, "pad_id": "A"},
            {"x": 1.0, "y": 0.0, "pad_id": "B"},
            {"x": 10.0, "y": 0.0, "pad_id": "C"},
        ]
        edges = compute_net_mst(pads)
        assert len(edges) == 2
        total = _total_length(edges)
        # MST connects 0→1 (1 mm) + 1→10 (9 mm) = 10 mm
        # Non-MST star from 0: 0→1 + 0→10 = 11 mm
        # MST length must be ≤ all other spanning topologies
        assert math.isclose(total, 10.0, rel_tol=1e-9)

    def test_square_four_pads_known_length(self):
        """MST on 4 pads at unit square corners has length 3 (picks 3 of 4 unit edges)."""
        # (0,0), (1,0), (0,1), (1,1) — all edge distances = 1, diagonals = √2
        pads = [
            {"x": 0.0, "y": 0.0, "pad_id": "TL"},
            {"x": 1.0, "y": 0.0, "pad_id": "TR"},
            {"x": 0.0, "y": 1.0, "pad_id": "BL"},
            {"x": 1.0, "y": 1.0, "pad_id": "BR"},
        ]
        edges = compute_net_mst(pads)
        assert len(edges) == 3
        total = _total_length(edges)
        # MST of unit-square = 3 unit edges (skip one unit edge or add no diagonals)
        assert math.isclose(total, 3.0, rel_tol=1e-9)

    def test_mst_minimal_vs_non_mst(self):
        """MST total length < naive all-edges-from-node-0 (star) topology."""
        # 5-node star would be sum of distances from node 0 to all others.
        # MST will avoid some of those long edges.
        pads = [
            {"x": 0.0, "y": 0.0, "pad_id": "p0"},
            {"x": 1.0, "y": 0.0, "pad_id": "p1"},
            {"x": 2.0, "y": 0.0, "pad_id": "p2"},
            {"x": 3.0, "y": 0.0, "pad_id": "p3"},
            {"x": 4.0, "y": 0.0, "pad_id": "p4"},
        ]
        edges = compute_net_mst(pads)
        mst_len = _total_length(edges)

        # Star from p0: distances 1+2+3+4 = 10
        star_len = sum(
            math.hypot(pads[i]["x"] - pads[0]["x"], pads[i]["y"] - pads[0]["y"])
            for i in range(1, len(pads))
        )
        # MST of collinear should be 4 (each adjacent pair = 1 mm apart)
        assert mst_len < star_len
        assert math.isclose(mst_len, 4.0, rel_tol=1e-9)

    def test_empty_pads(self):
        edges = compute_net_mst([])
        assert edges == []

    def test_single_pad(self):
        edges = compute_net_mst([{"x": 0.0, "y": 0.0, "pad_id": "only"}])
        assert edges == []

    def test_edge_fields(self):
        """Each edge has 'from', 'to', 'length_mm' keys."""
        pads = [
            {"x": 0.0, "y": 0.0, "pad_id": "A"},
            {"x": 5.0, "y": 0.0, "pad_id": "B"},
        ]
        edges = compute_net_mst(pads)
        assert len(edges) == 1
        e = edges[0]
        assert "from" in e and "to" in e and "length_mm" in e
        assert "pad_id" in e["from"]
        assert "pad_id" in e["to"]

    def test_diagonal_distance(self):
        """3-4-5 right triangle: MST picks the two shorter legs (3+4=7) not hypotenuse (5)."""
        pads = [
            {"x": 0.0, "y": 0.0, "pad_id": "origin"},
            {"x": 3.0, "y": 0.0, "pad_id": "x3"},
            {"x": 3.0, "y": 4.0, "pad_id": "x3y4"},
        ]
        edges = compute_net_mst(pads)
        total = _total_length(edges)
        # Legs: 3 + 4 = 7; hypotenuse alone does not span all 3 nodes
        assert math.isclose(total, 7.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# compute_ratsnest — integration tests
# ---------------------------------------------------------------------------

class TestComputeRatsnest:
    """Integration tests using full CircuitJSON arrays."""

    def test_simple_two_pad_net(self):
        circuit = [
            _make_pad("P1", 0.0, 0.0, "VCC"),
            _make_pad("P2", 5.0, 0.0, "VCC"),
        ]
        result = compute_ratsnest(circuit)
        assert len(result) == 1
        assert result[0]["net_id"] == "VCC"
        assert math.isclose(result[0]["length_mm"], 5.0, rel_tol=1e-9)

    def test_pads_without_net_ignored(self):
        circuit = [
            {"type": "pcb_smtpad", "pcb_smtpad_id": "P1", "x": 0.0, "y": 0.0},
            {"type": "pcb_smtpad", "pcb_smtpad_id": "P2", "x": 5.0, "y": 0.0},
        ]
        result = compute_ratsnest(circuit)
        assert result == []

    def test_multi_net_grouping(self):
        circuit = [
            _make_pad("A1", 0.0, 0.0, "NET_A"),
            _make_pad("A2", 1.0, 0.0, "NET_A"),
            _make_pad("B1", 10.0, 0.0, "NET_B"),
            _make_pad("B2", 12.0, 0.0, "NET_B"),
            _make_pad("B3", 14.0, 0.0, "NET_B"),
        ]
        result = compute_ratsnest(circuit)
        nets = {e["net_id"] for e in result}
        assert "NET_A" in nets
        assert "NET_B" in nets
        # NET_A: 2 pads → 1 edge; NET_B: 3 pads → 2 edges
        a_edges = [e for e in result if e["net_id"] == "NET_A"]
        b_edges = [e for e in result if e["net_id"] == "NET_B"]
        assert len(a_edges) == 1
        assert len(b_edges) == 2

    def test_single_pad_net_no_edges(self):
        circuit = [_make_pad("P1", 0.0, 0.0, "LONE")]
        result = compute_ratsnest(circuit)
        assert result == []

    def test_empty_circuit(self):
        assert compute_ratsnest([]) == []

    def test_non_list_returns_empty(self):
        assert compute_ratsnest(None) == []  # type: ignore[arg-type]

    def test_plated_holes_included(self):
        circuit = [
            {
                "type": "pcb_plated_hole",
                "pcb_plated_hole_id": "H1",
                "x": 0.0,
                "y": 0.0,
                "net_id": "GND",
            },
            {
                "type": "pcb_plated_hole",
                "pcb_plated_hole_id": "H2",
                "x": 3.0,
                "y": 4.0,
                "net_id": "GND",
            },
        ]
        result = compute_ratsnest(circuit)
        assert len(result) == 1
        assert math.isclose(result[0]["length_mm"], 5.0, rel_tol=1e-9)

    def test_result_has_required_keys(self):
        circuit = [
            _make_pad("P1", 0.0, 0.0, "V"),
            _make_pad("P2", 1.0, 0.0, "V"),
        ]
        result = compute_ratsnest(circuit)
        assert len(result) == 1
        edge = result[0]
        assert "net_id" in edge
        assert "from" in edge
        assert "to" in edge
        assert "length_mm" in edge

    def test_four_pad_square_mst_length(self):
        """MST of 4 pads at unit-square corners sums to 3 mm."""
        circuit = [
            _make_pad("TL", 0.0, 0.0, "N"),
            _make_pad("TR", 1.0, 0.0, "N"),
            _make_pad("BL", 0.0, 1.0, "N"),
            _make_pad("BR", 1.0, 1.0, "N"),
        ]
        result = compute_ratsnest(circuit)
        total = sum(e["length_mm"] for e in result)
        assert math.isclose(total, 3.0, rel_tol=1e-9)
