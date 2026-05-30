"""Tests for kerf_cad_core.geom.non_manifold.

Four analytical-oracle tests:
  1. T-junction edge detect  — body with 3 faces sharing one edge → 1 non-manifold edge.
  2. Repair-split mode       — same body → all edges ≤ 2 incident faces after repair;
                               stats.edges_split == 1.
  3. Manifold passthrough    — clean cube → detect returns empty; repair returns unchanged.
  4. Mesh equivalent         — mesh with one non-manifold vertex (touching cones) →
                               detect reports 1; repair via split fixes it.
"""

from __future__ import annotations

import copy

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
    make_box,
)
from kerf_cad_core.geom.non_manifold import (
    NonManifoldReport,
    MeshNonManifoldReport,
    RepairResult,
    MeshRepairResult,
    detect_non_manifold,
    detect_non_manifold_mesh,
    repair_non_manifold,
    repair_non_manifold_mesh,
)


# ---------------------------------------------------------------------------
# B-rep fixture helpers
# ---------------------------------------------------------------------------


def _make_t_junction_body() -> Body:
    """Build a body with 3 planar triangular faces that all share a single edge.

    This is a canonical T-junction: edge E shared by faces F1, F2, F3.
    Face layout:
      - F1: triangle (0,0,0) – (1,0,0) – (0.5,1,0) [the 'top' cap]
      - F2: triangle (0,0,0) – (1,0,0) – (0.5,0,-1) [hanging below]
      - F3: triangle (0,0,0) – (1,0,0) – (0.5,0, 1) [hanging above]
    All three share edge V0→V1 (the non-manifold edge).
    """
    tol = 1e-7
    P = [
        np.array([0.0, 0.0, 0.0]),   # 0
        np.array([1.0, 0.0, 0.0]),   # 1
        np.array([0.5, 1.0, 0.0]),   # 2
        np.array([0.5, 0.0, -1.0]),  # 3
        np.array([0.5, 0.0, 1.0]),   # 4
    ]
    V = [Vertex(p, tol) for p in P]

    # The shared non-manifold edge
    shared_edge = Edge(Line3(P[0], P[1]), 0.0, 1.0, V[0], V[1], tol)
    # Three private edges per face
    e02 = Edge(Line3(P[0], P[2]), 0.0, 1.0, V[0], V[2], tol)
    e12 = Edge(Line3(P[1], P[2]), 0.0, 1.0, V[1], V[2], tol)
    e03 = Edge(Line3(P[0], P[3]), 0.0, 1.0, V[0], V[3], tol)
    e13 = Edge(Line3(P[1], P[3]), 0.0, 1.0, V[1], V[3], tol)
    e04 = Edge(Line3(P[0], P[4]), 0.0, 1.0, V[0], V[4], tol)
    e14 = Edge(Line3(P[1], P[4]), 0.0, 1.0, V[1], V[4], tol)

    def _tri_face(v0, v1, v2, e_a, oa, e_b, ob, e_c, oc):
        plane = Plane(origin=v0.point, x_axis=v1.point - v0.point, y_axis=v2.point - v0.point)
        ces = [Coedge(e_a, oa), Coedge(e_b, ob), Coedge(e_c, oc)]
        loop = Loop(ces, is_outer=True)
        return Face(plane, [loop])

    # F1: V0→V1 (forward), V1→V2 (forward), V2→V0 (reverse of e02)
    f1 = _tri_face(V[0], V[1], V[2], shared_edge, True, e12, True, e02, False)
    # F2: V0→V1 (forward), V1→V3 (forward), V3→V0 (reverse of e03)
    f2 = _tri_face(V[0], V[1], V[3], shared_edge, True, e13, True, e03, False)
    # F3: V0→V1 (forward), V1→V4 (forward), V4→V0 (reverse of e04)
    f3 = _tri_face(V[0], V[1], V[4], shared_edge, True, e14, True, e04, False)

    shell = Shell([f1, f2, f3], is_closed=False)
    return Body(shells=[shell])


# ---------------------------------------------------------------------------
# Test 1: T-junction edge detect
# ---------------------------------------------------------------------------


def test_t_junction_detects_one_non_manifold_edge():
    """A body with 3 faces sharing one edge must report exactly 1 non-manifold edge."""
    body = _make_t_junction_body()
    report = detect_non_manifold(body)

    assert len(report.non_manifold_edges) == 1, (
        f"Expected 1 non-manifold edge, got {len(report.non_manifold_edges)}: "
        f"{report.non_manifold_edges}"
    )


def test_t_junction_no_false_positive_vertices():
    """The T-junction body has no disconnected vertex fans."""
    body = _make_t_junction_body()
    report = detect_non_manifold(body)
    # Vertices 0 and 1 (on the shared edge) have multiple incident faces —
    # but they are all mutually adjacent (shared edge), so the fan IS connected.
    assert len(report.non_manifold_vertices) == 0


def test_t_junction_not_manifold():
    body = _make_t_junction_body()
    report = detect_non_manifold(body)
    assert not report.is_manifold


# ---------------------------------------------------------------------------
# Test 2: Repair-split mode
# ---------------------------------------------------------------------------


def test_repair_split_fixes_t_junction():
    """After repair_non_manifold(mode='split'), no edge has > 2 incident faces."""
    body = _make_t_junction_body()
    result = repair_non_manifold(body, mode="split")

    # Verify all edges in repaired body have ≤ 2 incident faces
    e2f: dict = {}
    for face in result.body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                eid = ce.edge.id
                e2f.setdefault(eid, []).append(face.id)

    over_two = {eid: flist for eid, flist in e2f.items() if len(flist) > 2}
    assert len(over_two) == 0, f"Still non-manifold edges: {over_two}"


def test_repair_split_reports_edges_split():
    """Repair stats must record edges_split >= 1 for a T-junction."""
    body = _make_t_junction_body()
    result = repair_non_manifold(body, mode="split")
    assert result.stats.edges_split >= 1, (
        f"Expected edges_split >= 1, got {result.stats.edges_split}"
    )


def test_repair_split_adds_vertices():
    """Split mode inserts midpoint vertices (vertices_added >= 1)."""
    body = _make_t_junction_body()
    result = repair_non_manifold(body, mode="split")
    assert result.stats.vertices_added >= 1


def test_repair_does_not_mutate_input():
    """The original body must be unchanged after repair."""
    body = _make_t_junction_body()
    original_report = detect_non_manifold(body)
    repair_non_manifold(body, mode="split")
    after_report = detect_non_manifold(body)
    # Original should still be non-manifold
    assert len(after_report.non_manifold_edges) == len(original_report.non_manifold_edges)


# ---------------------------------------------------------------------------
# Test 3: Manifold passthrough (clean cube)
# ---------------------------------------------------------------------------


def test_cube_detect_returns_empty():
    """A clean cube B-rep must have no non-manifold elements."""
    body = make_box()
    report = detect_non_manifold(body)

    assert len(report.non_manifold_edges) == 0, (
        f"Cube has unexpected non-manifold edges: {report.non_manifold_edges}"
    )
    assert len(report.non_manifold_vertices) == 0, (
        f"Cube has unexpected non-manifold vertices: {report.non_manifold_vertices}"
    )
    assert len(report.non_manifold_faces) == 0, (
        f"Cube has unexpected non-manifold faces: {report.non_manifold_faces}"
    )


def test_cube_is_manifold():
    body = make_box()
    report = detect_non_manifold(body)
    assert report.is_manifold


def test_cube_repair_returns_unchanged_stats():
    """Repairing a clean cube should report zero changes."""
    body = make_box()
    result = repair_non_manifold(body, mode="split")
    assert result.stats.edges_split == 0
    assert result.stats.faces_deleted == 0
    assert result.stats.vertices_added == 0


def test_cube_repair_preserves_topology():
    """Repaired clean cube must have same face count."""
    body = make_box()
    result = repair_non_manifold(body)
    assert len(result.body.all_faces()) == len(body.all_faces())


# ---------------------------------------------------------------------------
# Test 4: Mesh equivalent — touching-cone vertex
# ---------------------------------------------------------------------------


def _make_touching_cone_mesh() -> dict:
    """Mesh with a non-manifold vertex (touching two triangle fans at a single vertex).

    Layout:
      Fan A: triangles sharing vertex 0 — [(0,1,2), (0,2,3)]
      Fan B: triangles sharing vertex 0 — [(0,4,5), (0,5,6)]
      The two fans touch at vertex 0 but share no edge incident to vertex 0 with
      each other, so vertex 0 is a non-manifold vertex (touching cone).

    Vertices:
      0 = origin (shared, non-manifold)
      1,2,3 = fan A
      4,5,6 = fan B (displaced in z so fans are spatially separated)
    """
    verts = [
        [0.0, 0.0, 0.0],  # 0 — shared vertex (non-manifold)
        [1.0, 0.0, 0.0],  # 1
        [0.5, 1.0, 0.0],  # 2
        [-0.5, 1.0, 0.0], # 3
        [1.0, 0.0, 2.0],  # 4  (fan B, z+2)
        [0.5, 1.0, 2.0],  # 5
        [-0.5, 1.0, 2.0], # 6
    ]
    faces = [
        [0, 1, 2],  # fan A
        [0, 2, 3],  # fan A
        [0, 4, 5],  # fan B
        [0, 5, 6],  # fan B
    ]
    return {"verts": verts, "faces": faces}


def test_mesh_touching_cone_detects_one_nm_vertex():
    """Mesh with 2 separate fans at one vertex → exactly 1 non-manifold vertex."""
    mesh = _make_touching_cone_mesh()
    report = detect_non_manifold_mesh(mesh)

    assert len(report.non_manifold_vertices) == 1, (
        f"Expected 1 non-manifold vertex, got {len(report.non_manifold_vertices)}: "
        f"{report.non_manifold_vertices}"
    )
    assert report.non_manifold_vertices[0] == 0


def test_mesh_touching_cone_not_manifold():
    mesh = _make_touching_cone_mesh()
    report = detect_non_manifold_mesh(mesh)
    assert not report.is_manifold


def test_mesh_repair_split_fixes_touching_cone():
    """After repair(mode='split') vertex 0 must no longer be non-manifold."""
    mesh = _make_touching_cone_mesh()
    result = repair_non_manifold_mesh(mesh, mode="split")

    after_report = detect_non_manifold_mesh({"verts": result.verts, "faces": result.faces})
    assert len(after_report.non_manifold_vertices) == 0, (
        f"Still has non-manifold vertices after repair: {after_report.non_manifold_vertices}"
    )


def test_mesh_repair_split_stats_vertices_split():
    """Split mode must report vertices_split >= 1."""
    mesh = _make_touching_cone_mesh()
    result = repair_non_manifold_mesh(mesh, mode="split")
    assert result.stats.vertices_split >= 1


def test_mesh_repair_preserves_face_count():
    """Split mode must not delete any faces."""
    mesh = _make_touching_cone_mesh()
    result = repair_non_manifold_mesh(mesh, mode="split")
    assert len(result.faces) == len(mesh["faces"]), (
        f"Face count changed: {len(mesh['faces'])} → {len(result.faces)}"
    )


def test_mesh_cube_is_manifold():
    """A clean cube mesh (12 triangles, all manifold) should report no issues."""
    verts = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 1.0, 1.0],
    ]
    faces = [
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [2, 3, 7], [2, 7, 6],
        [0, 4, 7], [0, 7, 3],
        [1, 2, 6], [1, 6, 5],
    ]
    mesh = {"verts": verts, "faces": faces}
    report = detect_non_manifold_mesh(mesh)
    assert report.is_manifold
    assert len(report.non_manifold_edges) == 0
    assert len(report.non_manifold_vertices) == 0


# ---------------------------------------------------------------------------
# Integration: heal_body repair_non_manifold kwarg
# ---------------------------------------------------------------------------


def test_heal_body_repair_non_manifold_kwarg():
    """heal_body(repair_non_manifold=True) must accept the kwarg without error."""
    from kerf_cad_core.geom.body_heal import heal_body
    body = make_box()
    healed = heal_body(body, repair_non_manifold=True)
    # Clean cube → still manifold after heal pass
    report = detect_non_manifold(healed)
    assert report.is_manifold


def test_heal_body_default_unchanged():
    """heal_body() without repair_non_manifold kwarg preserves existing behaviour."""
    from kerf_cad_core.geom.body_heal import heal_body
    body = make_box()
    healed = heal_body(body)
    assert len(healed.all_faces()) == len(body.all_faces())


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_detect_mesh_bad_input_raises():
    with pytest.raises(ValueError, match="must have"):
        detect_non_manifold_mesh({"bad": "input"})


def test_repair_mesh_bad_mode_raises():
    mesh = _make_touching_cone_mesh()
    with pytest.raises(ValueError, match="mode must be"):
        repair_non_manifold_mesh(mesh, mode="invalid")


def test_repair_brep_bad_mode_raises():
    body = make_box()
    with pytest.raises(ValueError, match="mode must be"):
        repair_non_manifold(body, mode="invalid")
