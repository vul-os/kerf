"""Hermetic tests for vertex_degree_check.py.

Oracle cases:

  1.  Cube (8 vertices, each degree 3): histogram {3:8}, boundary=0, non-manifold=0
      when expected_degree=3.
  2.  Cube with expected_degree=4: all 8 vertices appear as boundary (degree < 4).
  3.  Tetrahedron (4 vertices, each degree 3): histogram {3:4}, boundary=0, non-manifold=0
      with expected_degree=3.
  4.  Single quad face (4 vertices, degree 1 or 2): boundary > 0 for expected_degree >= 2.
  5.  Star vertex (1 vertex shared by 6 edges) → non-manifold at expected_degree=3.
  6.  Open mesh corner (degree 2 vertex) → boundary at expected_degree=3.
  7.  Degree histogram keys match actual degrees present.
  8.  max_degree correct for mixed-degree mesh.
  9.  Empty input returns zero-valued report.
  10. Single edge (2 degree-1 vertices) → both boundary at expected_degree=2.
  11. Two disconnected triangles sharing no vertices: degree histogram correct.
  12. Report.as_dict() roundtrip preserves all fields.
  13. irregular_vertex_indices includes all boundary + non-manifold ids.
  14. num_vertices matches total distinct vertex count.
  15. expected_degree=1 → no boundary vertices on any connected edge.
  16. Re-export from geom/__init__.py works.
"""

from __future__ import annotations

import pytest
from kerf_cad_core.geom.vertex_degree_check import (
    VertexDegreeReport,
    check_vertex_degrees,
    _make_cube_face_list,
    _make_tetrahedron_face_list,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _single_quad_faces() -> list:
    """One quad face: 4 vertices, each incident on 2 edges of the boundary loop."""
    return [
        {
            "face_id": "f0",
            "edges": [
                {"edge_id": "e0", "start": "v0", "end": "v1"},
                {"edge_id": "e1", "start": "v1", "end": "v2"},
                {"edge_id": "e2", "start": "v2", "end": "v3"},
                {"edge_id": "e3", "start": "v3", "end": "v0"},
            ],
        }
    ]


def _star_vertex_faces(fan_size: int = 6) -> list:
    """One central vertex 'vc' connected to fan_size outer vertices.

    Each spoke is shared by two triangular faces, so vc has degree == fan_size.
    Outer vertices have degree 2 each (one spoke + one rim edge).
    """
    faces = []
    outer = [f"vo{i}" for i in range(fan_size)]
    for i in range(fan_size):
        a = outer[i]
        b = outer[(i + 1) % fan_size]
        spoke_a = f"spoke_{i}"
        spoke_b = f"spoke_{(i + 1) % fan_size}"
        rim = f"rim_{i}"
        faces.append({
            "face_id": f"f{i}",
            "edges": [
                {"edge_id": spoke_a, "start": "vc", "end": a},
                {"edge_id": rim,     "start": a,    "end": b},
                {"edge_id": spoke_b, "start": "vc", "end": b},
            ],
        })
    return faces


def _open_mesh_corner_faces() -> list:
    """Two adjacent triangles in an open mesh.

    Two triangles:
        f0: v0-v1, v1-v2, v0-v2
        f1: v1-v2, v2-v3, v1-v3

    v0: degree 2 (e01, e02)  -> boundary at expected_degree=3
    v1: degree 3 (e01, e12, e13)
    v2: degree 3 (e02, e12, e23)
    v3: degree 2 (e13, e23)  -> boundary at expected_degree=3
    """
    return [
        {
            "face_id": "f0",
            "edges": [
                {"edge_id": "e01", "start": "v0", "end": "v1"},
                {"edge_id": "e12", "start": "v1", "end": "v2"},
                {"edge_id": "e02", "start": "v0", "end": "v2"},
            ],
        },
        {
            "face_id": "f1",
            "edges": [
                {"edge_id": "e12", "start": "v1", "end": "v2"},
                {"edge_id": "e23", "start": "v2", "end": "v3"},
                {"edge_id": "e13", "start": "v1", "end": "v3"},
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Test 1: Cube, expected_degree=3 → no irregular vertices
# ---------------------------------------------------------------------------

def test_cube_degree3_no_irregular():
    """Cube: 8 vertices each at degree 3; no boundary or non-manifold at expected=3."""
    faces = _make_cube_face_list()
    r = check_vertex_degrees(faces, expected_degree=3)

    assert r.num_vertices == 8
    assert r.degree_histogram == {3: 8}, f"histogram: {r.degree_histogram}"
    assert r.num_boundary_vertices == 0
    assert r.num_non_manifold_vertices == 0
    assert r.max_degree == 3
    assert r.irregular_vertex_indices == []


# ---------------------------------------------------------------------------
# Test 2: Cube, expected_degree=4 → all 8 vertices boundary (degree 3 < 4)
# ---------------------------------------------------------------------------

def test_cube_expected_degree4_all_boundary():
    """Cube corners all have degree 3 < 4; all flagged boundary."""
    faces = _make_cube_face_list()
    r = check_vertex_degrees(faces, expected_degree=4)

    assert r.num_vertices == 8
    assert r.num_boundary_vertices == 8
    assert r.num_non_manifold_vertices == 0
    assert len(r.irregular_vertex_indices) == 8


# ---------------------------------------------------------------------------
# Test 3: Tetrahedron, expected_degree=3 → no irregular vertices
# ---------------------------------------------------------------------------

def test_tetrahedron_degree3():
    """Tetrahedron: 4 vertices each at degree 3; histogram {3:4}."""
    faces = _make_tetrahedron_face_list()
    r = check_vertex_degrees(faces, expected_degree=3)

    assert r.num_vertices == 4
    assert r.degree_histogram == {3: 4}
    assert r.num_boundary_vertices == 0
    assert r.num_non_manifold_vertices == 0
    assert r.max_degree == 3


# ---------------------------------------------------------------------------
# Test 4: Single quad face — 4 vertices at degree 2; all boundary at expected=3
# ---------------------------------------------------------------------------

def test_single_quad_boundary_vertices():
    """Single quad face: each corner has degree 2 < 3 → all boundary."""
    faces = _single_quad_faces()
    r = check_vertex_degrees(faces, expected_degree=3)

    assert r.num_vertices == 4
    assert r.degree_histogram == {2: 4}
    assert r.num_boundary_vertices == 4
    assert r.num_non_manifold_vertices == 0


# ---------------------------------------------------------------------------
# Test 5: Star vertex (6-fan) → non-manifold at expected_degree=3
# ---------------------------------------------------------------------------

def test_star_vertex_nonmanifold():
    """Central vertex shared by 6-fan is non-manifold at expected_degree=3 (6 > 3+2=5)."""
    faces = _star_vertex_faces(fan_size=6)
    r = check_vertex_degrees(faces, expected_degree=3)

    assert r.num_non_manifold_vertices >= 1, (
        f"expected central vertex non-manifold, got {r.num_non_manifold_vertices}; "
        f"histogram={r.degree_histogram}"
    )
    assert "vc" in r.irregular_vertex_indices


# ---------------------------------------------------------------------------
# Test 6: Open mesh corner — two open-boundary vertices at degree 2
# ---------------------------------------------------------------------------

def test_open_mesh_boundary_vertices():
    """Open mesh: v0 and v3 have degree 2, boundary at expected_degree=3."""
    faces = _open_mesh_corner_faces()
    r = check_vertex_degrees(faces, expected_degree=3)

    assert r.num_vertices == 4
    assert r.num_boundary_vertices == 2
    assert r.num_non_manifold_vertices == 0
    # v0 and v3 flagged
    assert "v0" in r.irregular_vertex_indices
    assert "v3" in r.irregular_vertex_indices


# ---------------------------------------------------------------------------
# Test 7: Histogram keys match degrees present
# ---------------------------------------------------------------------------

def test_histogram_keys_match_actual_degrees():
    """Every key in degree_histogram corresponds to an actual observed degree."""
    faces = _open_mesh_corner_faces()
    r = check_vertex_degrees(faces, expected_degree=3)

    all_degrees = set(r.degree_histogram.keys())
    # We know this mesh has only degree-2 and degree-3 vertices
    assert all_degrees == {2, 3}, f"unexpected degrees: {all_degrees}"
    assert r.degree_histogram[2] == 2  # v0, v3
    assert r.degree_histogram[3] == 2  # v1, v2


# ---------------------------------------------------------------------------
# Test 8: max_degree is correct
# ---------------------------------------------------------------------------

def test_max_degree_star_vertex():
    """max_degree should equal the fan count for the central vertex."""
    for fan in [4, 5, 7]:
        faces = _star_vertex_faces(fan_size=fan)
        r = check_vertex_degrees(faces, expected_degree=3)
        assert r.max_degree == fan, f"fan={fan}: max_degree={r.max_degree}"


# ---------------------------------------------------------------------------
# Test 9: Empty input returns zeroed report
# ---------------------------------------------------------------------------

def test_empty_input():
    """Empty face list → zero-valued report."""
    r = check_vertex_degrees([], expected_degree=4)
    assert r.num_vertices == 0
    assert r.degree_histogram == {}
    assert r.num_boundary_vertices == 0
    assert r.num_non_manifold_vertices == 0
    assert r.max_degree == 0
    assert r.irregular_vertex_indices == []


# ---------------------------------------------------------------------------
# Test 10: Single edge (2 degree-1 vertices) → both boundary at expected=2
# ---------------------------------------------------------------------------

def test_single_edge_boundary():
    """One face with one edge: 2 degree-1 vertices, both boundary at expected=2."""
    faces = [
        {
            "face_id": "f0",
            "edges": [{"edge_id": "e0", "start": "va", "end": "vb"}],
        }
    ]
    r = check_vertex_degrees(faces, expected_degree=2)

    assert r.num_vertices == 2
    assert r.degree_histogram == {1: 2}
    assert r.num_boundary_vertices == 2
    assert r.num_non_manifold_vertices == 0


# ---------------------------------------------------------------------------
# Test 11: Two disconnected triangles
# ---------------------------------------------------------------------------

def test_two_disconnected_triangles():
    """Two triangles sharing no vertices: 6 distinct degree-2 vertices."""
    tri1 = [
        {"face_id": "f0", "edges": [
            {"edge_id": "e0", "start": "a0", "end": "a1"},
            {"edge_id": "e1", "start": "a1", "end": "a2"},
            {"edge_id": "e2", "start": "a0", "end": "a2"},
        ]}
    ]
    tri2 = [
        {"face_id": "f1", "edges": [
            {"edge_id": "e3", "start": "b0", "end": "b1"},
            {"edge_id": "e4", "start": "b1", "end": "b2"},
            {"edge_id": "e5", "start": "b0", "end": "b2"},
        ]}
    ]
    r = check_vertex_degrees(tri1 + tri2, expected_degree=3)
    assert r.num_vertices == 6
    assert r.degree_histogram == {2: 6}
    assert r.num_boundary_vertices == 6
    assert r.num_non_manifold_vertices == 0


# ---------------------------------------------------------------------------
# Test 12: as_dict() roundtrip
# ---------------------------------------------------------------------------

def test_as_dict_roundtrip():
    """as_dict() contains all required keys and matches report attributes."""
    faces = _make_cube_face_list()
    r = check_vertex_degrees(faces, expected_degree=3)
    d = r.as_dict()

    required_keys = {
        "num_vertices",
        "degree_histogram",
        "num_boundary_vertices",
        "num_non_manifold_vertices",
        "max_degree",
        "irregular_vertex_indices",
        "honest_caveat",
    }
    assert required_keys.issubset(d.keys()), f"missing keys: {required_keys - d.keys()}"
    assert d["num_vertices"] == r.num_vertices
    assert d["degree_histogram"] == r.degree_histogram
    assert d["max_degree"] == r.max_degree
    assert isinstance(d["honest_caveat"], str) and len(d["honest_caveat"]) > 0


# ---------------------------------------------------------------------------
# Test 13: irregular_vertex_indices covers boundary + non-manifold
# ---------------------------------------------------------------------------

def test_irregular_indices_cover_all_flagged():
    """irregular_vertex_indices must include both boundary and non-manifold vertices."""
    # Build a mesh that has both: open strip (boundary) + star (non-manifold)
    strip = _open_mesh_corner_faces()           # v0, v3 = boundary
    star = _star_vertex_faces(fan_size=6)       # vc = non-manifold

    # Rename star vertices to avoid collision with strip vertices
    renamed = []
    for face in star:
        new_edges = []
        for e in face["edges"]:
            new_edges.append({
                "edge_id": "s_" + e["edge_id"],
                "start": "s_" + e["start"],
                "end": "s_" + e["end"],
            })
        renamed.append({"face_id": "s_" + face["face_id"], "edges": new_edges})

    r = check_vertex_degrees(strip + renamed, expected_degree=3)
    assert r.num_boundary_vertices >= 2
    assert r.num_non_manifold_vertices >= 1
    assert "v0" in r.irregular_vertex_indices
    assert "v3" in r.irregular_vertex_indices
    assert "s_vc" in r.irregular_vertex_indices


# ---------------------------------------------------------------------------
# Test 14: num_vertices matches distinct vertex count
# ---------------------------------------------------------------------------

def test_num_vertices_distinct_count():
    """num_vertices is distinct vertices, not edges*2."""
    faces = _make_cube_face_list()
    r = check_vertex_degrees(faces, expected_degree=3)
    assert r.num_vertices == 8  # cube has 8 corners, not 12*2=24


# ---------------------------------------------------------------------------
# Test 15: expected_degree=1 → no boundary on any connected edge
# ---------------------------------------------------------------------------

def test_expected_degree_1_no_boundary():
    """With expected_degree=1, any vertex with ≥1 edge is not boundary."""
    faces = _single_quad_faces()
    r = check_vertex_degrees(faces, expected_degree=1)
    assert r.num_boundary_vertices == 0


# ---------------------------------------------------------------------------
# Test 16: Re-export from geom/__init__.py
# ---------------------------------------------------------------------------

def test_reexport_from_geom_init():
    """VertexDegreeReport and check_vertex_degrees must be importable from geom."""
    from kerf_cad_core.geom import VertexDegreeReport as VDR, check_vertex_degrees as cvd
    assert VDR is VertexDegreeReport
    assert cvd is check_vertex_degrees


# ---------------------------------------------------------------------------
# Test 17: 4-fan star vertex is NOT non-manifold at expected_degree=3 (4 <= 3+2=5)
# ---------------------------------------------------------------------------

def test_star_vertex_4fan_not_nonmanifold_at_expected3():
    """A 4-fan vertex has degree 4, which is <= expected(3)+2=5, so not flagged."""
    faces = _star_vertex_faces(fan_size=4)
    r = check_vertex_degrees(faces, expected_degree=3)
    assert r.num_non_manifold_vertices == 0, (
        f"4-fan should not be non-manifold at expected=3, got {r.num_non_manifold_vertices}"
    )


# ---------------------------------------------------------------------------
# Test 18: 8-fan star vertex IS non-manifold at expected_degree=4 (8 > 4+2=6)
# ---------------------------------------------------------------------------

def test_star_vertex_8fan_nonmanifold_at_expected4():
    """An 8-fan vertex has degree 8 > 4+2=6 → non-manifold at expected_degree=4."""
    faces = _star_vertex_faces(fan_size=8)
    r = check_vertex_degrees(faces, expected_degree=4)
    assert r.num_non_manifold_vertices >= 1


# ---------------------------------------------------------------------------
# Test 19: Tetrahedron at default expected_degree=4 — all 4 vertices boundary
# ---------------------------------------------------------------------------

def test_tetrahedron_at_default_expected_degree():
    """Tetrahedron degree-3 vertices all flagged boundary at default expected_degree=4."""
    faces = _make_tetrahedron_face_list()
    r = check_vertex_degrees(faces)  # default expected_degree=4
    assert r.num_boundary_vertices == 4
    assert r.num_non_manifold_vertices == 0


# ---------------------------------------------------------------------------
# Test 20: Duplicate edge appearances in different faces don't double-count
# ---------------------------------------------------------------------------

def test_duplicate_edge_in_face_list_not_double_counted():
    """Same edge_id appearing in multiple face lists should count once per vertex."""
    # Two faces that share edge e01 (shared interior edge)
    faces = [
        {"face_id": "f0", "edges": [
            {"edge_id": "e01", "start": "v0", "end": "v1"},
            {"edge_id": "e12", "start": "v1", "end": "v2"},
            {"edge_id": "e02", "start": "v0", "end": "v2"},
        ]},
        {"face_id": "f1", "edges": [
            {"edge_id": "e01", "start": "v0", "end": "v1"},  # same edge, different face
            {"edge_id": "e13", "start": "v1", "end": "v3"},
            {"edge_id": "e03", "start": "v0", "end": "v3"},
        ]},
    ]
    r = check_vertex_degrees(faces, expected_degree=3)
    # v0: e01, e02, e03 = 3
    # v1: e01, e12, e13 = 3
    # v2: e12, e02 = 2
    # v3: e13, e03 = 2
    assert r.num_vertices == 4
    # v0, v1 should be degree 3; v2, v3 degree 2
    assert r.degree_histogram.get(3, 0) == 2
    assert r.degree_histogram.get(2, 0) == 2
