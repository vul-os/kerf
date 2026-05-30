"""Tests for BREP-FACE-NEIGHBOR-WALK.

Oracles
-------
Unit cube (6 faces, each sharing 4 edges with 4 distinct neighbours, 1 pair of
opposite faces sharing no edge):
  - Every face has exactly 4 neighbours.
  - BFS from face 0: depth-1 = 4 faces, depth-2 = 1 face (the opposite face).
  - Shortest path between face 0 and its opposite = 2 hops (length-3 list).

Open cylinder shell (3 faces: 1 cylindrical side + 2 end caps):
  - Side shares one edge with each cap → side has 2 neighbours.
  - Caps share no edge with each other → each cap has exactly 1 neighbour.

Honest-flag tests: point-touching faces (vertex-only contact) must NOT appear
as adjacent.
"""

from __future__ import annotations

import pytest

from kerf_cad_core.geom.face_neighbor_walk import (
    FaceAdjacencyGraph,
    bfs_from_face,
    face_adjacency_graph,
    face_neighbors,
    shortest_face_path,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_cube_faces():
    """Return 6 face dicts for a unit cube.

    Cube faces and their shared edges (one edge per pair of adjacent faces):
      face 0 (bottom): edges e01, e02, e03, e04
      face 1 (front):  edges e01, e12, e15, e16
      face 2 (right):  edges e02, e12, e23, e26
      face 3 (back):   edges e03, e23, e34, e36
      face 4 (left):   edges e04, e15, e34, e45
      face 5 (top):    edges e16, e26, e36, e45

    Adjacency pattern:
      0 ↔ 1, 0 ↔ 2, 0 ↔ 3, 0 ↔ 4  (bottom touches front/right/back/left)
      5 ↔ 1, 5 ↔ 2, 5 ↔ 3, 5 ↔ 4  (top touches front/right/back/left)
      NO 0↔5 (bottom↔top are opposite faces, no shared edge)
      NO 1↔3, NO 2↔4 (other opposite pairs)
    """
    return [
        {"face_id": 0, "edges": [{"edge_id": "e01"}, {"edge_id": "e02"}, {"edge_id": "e03"}, {"edge_id": "e04"}]},
        {"face_id": 1, "edges": [{"edge_id": "e01"}, {"edge_id": "e12"}, {"edge_id": "e15"}, {"edge_id": "e16"}]},
        {"face_id": 2, "edges": [{"edge_id": "e02"}, {"edge_id": "e12"}, {"edge_id": "e23"}, {"edge_id": "e26"}]},
        {"face_id": 3, "edges": [{"edge_id": "e03"}, {"edge_id": "e23"}, {"edge_id": "e34"}, {"edge_id": "e36"}]},
        {"face_id": 4, "edges": [{"edge_id": "e04"}, {"edge_id": "e15"}, {"edge_id": "e34"}, {"edge_id": "e45"}]},
        {"face_id": 5, "edges": [{"edge_id": "e16"}, {"edge_id": "e26"}, {"edge_id": "e36"}, {"edge_id": "e45"}]},
    ]


def _make_cylinder_faces():
    """Return 3 face dicts for an open cylinder shell.

    face 0 (side):    edges eA (top circle), eB (bottom circle)
    face 1 (top cap): edges eA
    face 2 (bot cap): edges eB

    Adjacency: side↔top, side↔bot; top and bot do NOT share any edge.
    """
    return [
        {"face_id": "side", "edges": [{"edge_id": "eA"}, {"edge_id": "eB"}]},
        {"face_id": "top",  "edges": [{"edge_id": "eA"}]},
        {"face_id": "bot",  "edges": [{"edge_id": "eB"}]},
    ]


# ---------------------------------------------------------------------------
# face_adjacency_graph
# ---------------------------------------------------------------------------

class TestFaceAdjacencyGraph:
    def test_empty_returns_empty(self):
        assert face_adjacency_graph([]) == {}

    def test_single_face_isolated(self):
        faces = [{"face_id": "f0", "edges": [{"edge_id": "e1"}]}]
        g = face_adjacency_graph(faces)
        assert g == {"f0": set()}

    def test_cube_all_keys_present(self):
        g = face_adjacency_graph(_make_cube_faces())
        assert set(g.keys()) == {0, 1, 2, 3, 4, 5}

    def test_cube_every_face_has_4_neighbours(self):
        g = face_adjacency_graph(_make_cube_faces())
        for fid, nbrs in g.items():
            assert len(nbrs) == 4, f"face {fid} has {len(nbrs)} neighbours, expected 4"

    def test_cube_opposite_faces_not_adjacent(self):
        g = face_adjacency_graph(_make_cube_faces())
        assert 5 not in g[0]
        assert 0 not in g[5]
        assert 3 not in g[1]
        assert 1 not in g[3]
        assert 4 not in g[2]
        assert 2 not in g[4]

    def test_cube_known_adjacency(self):
        g = face_adjacency_graph(_make_cube_faces())
        assert 1 in g[0] and 2 in g[0] and 3 in g[0] and 4 in g[0]

    def test_cylinder_side_has_2_neighbours(self):
        g = face_adjacency_graph(_make_cylinder_faces())
        assert len(g["side"]) == 2
        assert "top" in g["side"]
        assert "bot" in g["side"]

    def test_cylinder_caps_not_adjacent_to_each_other(self):
        g = face_adjacency_graph(_make_cylinder_faces())
        assert "bot" not in g["top"]
        assert "top" not in g["bot"]

    def test_cylinder_each_cap_has_1_neighbour(self):
        g = face_adjacency_graph(_make_cylinder_faces())
        assert g["top"] == {"side"}
        assert g["bot"] == {"side"}

    def test_no_edges_face_is_isolated(self):
        faces = [
            {"face_id": "a", "edges": []},
            {"face_id": "b", "edges": []},
        ]
        g = face_adjacency_graph(faces)
        assert g["a"] == set()
        assert g["b"] == set()

    def test_face_id_fallback_to_index(self):
        # No face_id field — should fall back to integer index
        faces = [
            {"edges": [{"edge_id": "e1"}]},
            {"edges": [{"edge_id": "e1"}]},
        ]
        g = face_adjacency_graph(faces)
        assert 0 in g and 1 in g
        assert 1 in g[0] and 0 in g[1]

    def test_disconnected_two_cubes(self):
        """Two non-overlapping cubes → 2 connected components."""
        cube_a = _make_cube_faces()  # edges eXX
        # Cube B uses entirely different edge ids to avoid false adjacency
        cube_b = [
            {"face_id": 10, "edges": [{"edge_id": "f01"}, {"edge_id": "f02"}, {"edge_id": "f03"}, {"edge_id": "f04"}]},
            {"face_id": 11, "edges": [{"edge_id": "f01"}, {"edge_id": "f12"}, {"edge_id": "f15"}, {"edge_id": "f16"}]},
            {"face_id": 12, "edges": [{"edge_id": "f02"}, {"edge_id": "f12"}, {"edge_id": "f23"}, {"edge_id": "f26"}]},
            {"face_id": 13, "edges": [{"edge_id": "f03"}, {"edge_id": "f23"}, {"edge_id": "f34"}, {"edge_id": "f36"}]},
            {"face_id": 14, "edges": [{"edge_id": "f04"}, {"edge_id": "f15"}, {"edge_id": "f34"}, {"edge_id": "f45"}]},
            {"face_id": 15, "edges": [{"edge_id": "f16"}, {"edge_id": "f26"}, {"edge_id": "f36"}, {"edge_id": "f45"}]},
        ]
        fag = FaceAdjacencyGraph.from_faces(cube_a + cube_b)
        components = fag.connected_components()
        assert len(components) == 2

        face_sets = [frozenset(c) for c in components]
        comp_a = frozenset({0, 1, 2, 3, 4, 5})
        comp_b = frozenset({10, 11, 12, 13, 14, 15})
        assert comp_a in face_sets
        assert comp_b in face_sets


# ---------------------------------------------------------------------------
# face_neighbors
# ---------------------------------------------------------------------------

class TestFaceNeighbors:
    def test_cube_face_0_has_4_neighbours(self):
        nbrs = face_neighbors(0, _make_cube_faces())
        assert set(nbrs) == {1, 2, 3, 4}

    def test_cube_face_5_has_4_neighbours(self):
        nbrs = face_neighbors(5, _make_cube_faces())
        assert set(nbrs) == {1, 2, 3, 4}

    def test_cylinder_side_neighbours(self):
        nbrs = face_neighbors("side", _make_cylinder_faces())
        assert set(nbrs) == {"top", "bot"}

    def test_unknown_face_returns_empty(self):
        nbrs = face_neighbors("NOSUCHFACE", _make_cube_faces())
        assert nbrs == []

    def test_empty_faces_returns_empty(self):
        assert face_neighbors(0, []) == []


# ---------------------------------------------------------------------------
# bfs_from_face
# ---------------------------------------------------------------------------

class TestBfsFromFace:
    def test_cube_depth1_from_face0(self):
        result = bfs_from_face(0, _make_cube_faces(), depth_cap=1)
        assert result[0] == 0
        # Depth-1: the 4 neighbours
        depth1 = {fid for fid, d in result.items() if d == 1}
        assert depth1 == {1, 2, 3, 4}
        # Opposite face (5) should NOT be reached at depth_cap=1
        assert 5 not in result

    def test_cube_depth2_reaches_opposite_face(self):
        result = bfs_from_face(0, _make_cube_faces(), depth_cap=2)
        assert result.get(5) == 2

    def test_cube_full_bfs_covers_all_6(self):
        result = bfs_from_face(0, _make_cube_faces(), depth_cap=10)
        assert set(result.keys()) == {0, 1, 2, 3, 4, 5}

    def test_bfs_depth0_returns_only_start(self):
        result = bfs_from_face(0, _make_cube_faces(), depth_cap=0)
        assert result == {0: 0}

    def test_bfs_unknown_start_returns_empty(self):
        result = bfs_from_face(99, _make_cube_faces(), depth_cap=5)
        assert result == {}

    def test_bfs_empty_faces(self):
        assert bfs_from_face(0, [], depth_cap=5) == {}

    def test_cylinder_bfs_from_side(self):
        result = bfs_from_face("side", _make_cylinder_faces(), depth_cap=10)
        assert result == {"side": 0, "top": 1, "bot": 1}

    def test_cylinder_bfs_from_top(self):
        result = bfs_from_face("top", _make_cylinder_faces(), depth_cap=10)
        assert result["top"] == 0
        assert result["side"] == 1
        assert result["bot"] == 2


# ---------------------------------------------------------------------------
# shortest_face_path
# ---------------------------------------------------------------------------

class TestShortestFacePath:
    def test_cube_same_face(self):
        path = shortest_face_path(0, 0, _make_cube_faces())
        assert path == [0]

    def test_cube_adjacent_faces_1_hop(self):
        path = shortest_face_path(0, 1, _make_cube_faces())
        assert path[0] == 0
        assert path[-1] == 1
        assert len(path) == 2  # [0, 1]

    def test_cube_opposite_faces_2_hops(self):
        path = shortest_face_path(0, 5, _make_cube_faces())
        assert path[0] == 0
        assert path[-1] == 5
        assert len(path) == 3  # exactly 2 hops

    def test_cube_path_is_valid_traversal(self):
        """Every consecutive pair in the path must be adjacent."""
        faces = _make_cube_faces()
        graph = face_adjacency_graph(faces)
        for start in range(6):
            for end in range(6):
                path = shortest_face_path(start, end, faces)
                if start == end:
                    assert len(path) == 1
                    continue
                assert len(path) >= 2
                for i in range(len(path) - 1):
                    assert path[i + 1] in graph[path[i]], (
                        f"path {path}: {path[i]} not adjacent to {path[i+1]}"
                    )

    def test_disconnected_returns_empty(self):
        """Faces in different components have no path."""
        cube_b_faces = [
            {"face_id": 10, "edges": [{"edge_id": "fX1"}]},
            {"face_id": 11, "edges": [{"edge_id": "fX2"}]},
        ]
        path = shortest_face_path(0, 10, _make_cube_faces() + cube_b_faces)
        assert path == []

    def test_unknown_start_returns_empty(self):
        assert shortest_face_path(99, 0, _make_cube_faces()) == []

    def test_unknown_end_returns_empty(self):
        assert shortest_face_path(0, 99, _make_cube_faces()) == []

    def test_empty_faces_returns_empty(self):
        assert shortest_face_path(0, 1, []) == []

    def test_cylinder_cap_to_cap_path_through_side(self):
        path = shortest_face_path("top", "bot", _make_cylinder_faces())
        assert path == ["top", "side", "bot"] or path == ["bot", "side", "top"]  # BFS is symmetric
        assert set(path) == {"top", "side", "bot"}
        assert len(path) == 3


# ---------------------------------------------------------------------------
# FaceAdjacencyGraph dataclass
# ---------------------------------------------------------------------------

class TestFaceAdjacencyGraphDataclass:
    def test_from_faces_builds_graph(self):
        fag = FaceAdjacencyGraph.from_faces(_make_cube_faces())
        assert len(fag.graph) == 6

    def test_neighbors_delegate(self):
        fag = FaceAdjacencyGraph.from_faces(_make_cube_faces())
        assert set(fag.neighbors(0)) == {1, 2, 3, 4}

    def test_bfs_delegate(self):
        fag = FaceAdjacencyGraph.from_faces(_make_cube_faces())
        result = fag.bfs(0, depth_cap=2)
        assert result.get(5) == 2

    def test_shortest_path_delegate(self):
        fag = FaceAdjacencyGraph.from_faces(_make_cube_faces())
        path = fag.shortest_path(0, 5)
        assert len(path) == 3

    def test_connected_components_cube(self):
        fag = FaceAdjacencyGraph.from_faces(_make_cube_faces())
        comps = fag.connected_components()
        assert len(comps) == 1
        assert comps[0] == {0, 1, 2, 3, 4, 5}

    def test_connected_components_empty(self):
        fag = FaceAdjacencyGraph.from_faces([])
        assert fag.connected_components() == []

    def test_point_touching_not_adjacent(self):
        """Vertex-only contact must NOT create adjacency (honest-flag test)."""
        # Two squares sharing only a corner vertex but no edge id
        faces = [
            {"face_id": "sq1", "edges": [{"edge_id": "e1"}, {"edge_id": "e2"}]},
            {"face_id": "sq2", "edges": [{"edge_id": "e3"}, {"edge_id": "e4"}]},
        ]
        fag = FaceAdjacencyGraph.from_faces(faces)
        assert fag.graph["sq1"] == set()
        assert fag.graph["sq2"] == set()
