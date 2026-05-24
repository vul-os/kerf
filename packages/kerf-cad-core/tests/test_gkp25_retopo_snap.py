"""Tests for GK-P25: retopo_snap — project cage verts onto source surface."""
from __future__ import annotations
import math
import pytest
from kerf_cad_core.geom.subd_authoring import SubDCage, retopo_snap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_unit_cage() -> SubDCage:
    """Simple 4-vertex quad cage floating above the XY plane."""
    verts = [
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 1.0],
        [1.0, 1.0, 1.0],
        [0.0, 1.0, 1.0],
    ]
    return SubDCage(vertices=verts, faces=[[0, 1, 2, 3]])


def make_flat_plane_mesh():
    """A 2×2 grid of triangles in the XY plane (z=0)."""
    verts = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
        [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], [2.0, 1.0, 0.0],
        [0.0, 2.0, 0.0], [1.0, 2.0, 0.0], [2.0, 2.0, 0.0],
    ]
    # 8 triangles covering the 2×2 grid
    faces = [
        [0, 1, 4], [0, 4, 3],
        [1, 2, 5], [1, 5, 4],
        [3, 4, 7], [3, 7, 6],
        [4, 5, 8], [4, 8, 7],
    ]
    return {"vertices": verts, "faces": faces}


def make_sphere_mesh_approx():
    """A rough octahedron as stand-in for a sphere-like mesh."""
    verts = [
        [ 0.0,  0.0,  1.0],
        [ 1.0,  0.0,  0.0],
        [ 0.0,  1.0,  0.0],
        [-1.0,  0.0,  0.0],
        [ 0.0, -1.0,  0.0],
        [ 0.0,  0.0, -1.0],
    ]
    faces = [
        [0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
        [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4],
    ]
    return {"vertices": verts, "faces": faces}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRetopoSnap:
    def test_returns_cage_same_vertex_count(self):
        cage = make_unit_cage()
        src = make_flat_plane_mesh()
        result = retopo_snap(src, cage)
        assert isinstance(result, SubDCage)
        assert len(result.vertices) == len(cage.vertices)

    def test_returns_cage_same_faces(self):
        cage = make_unit_cage()
        src = make_flat_plane_mesh()
        result = retopo_snap(src, cage)
        assert result.faces == cage.faces

    def test_flat_plane_snaps_z_to_zero(self):
        """Cage verts at z=1 should snap onto the z=0 plane."""
        cage = make_unit_cage()
        src = make_flat_plane_mesh()
        result = retopo_snap(src, cage)
        for v in result.vertices:
            assert abs(v[2]) < 0.01, f"z should be ~0 after snap, got {v[2]}"

    def test_snap_preserves_xy(self):
        """For a flat plane at z=0, XY coords should be preserved."""
        cage = make_unit_cage()
        src = make_flat_plane_mesh()
        result = retopo_snap(src, cage)
        for orig, snapped in zip(cage.vertices, result.vertices):
            assert abs(orig[0] - snapped[0]) < 0.5, "X changed too much"
            assert abs(orig[1] - snapped[1]) < 0.5, "Y changed too much"

    def test_snap_vertices_all_finite(self):
        cage = make_unit_cage()
        src = make_sphere_mesh_approx()
        result = retopo_snap(src, cage)
        for v in result.vertices:
            for coord in v:
                assert math.isfinite(coord), f"Non-finite coord after snap: {coord}"

    def test_snap_empty_source_returns_copy(self):
        cage = make_unit_cage()
        result = retopo_snap({"vertices": [], "faces": []}, cage)
        assert result.vertices == cage.vertices

    def test_snap_source_no_faces_returns_copy(self):
        cage = make_unit_cage()
        verts = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        result = retopo_snap({"vertices": verts, "faces": []}, cage)
        assert result.vertices == cage.vertices

    def test_snap_onto_sphere_moves_verts_closer(self):
        """Cage at z=2 snaps onto octahedron: verts should move toward surface."""
        cage = SubDCage(
            vertices=[[0.0, 0.0, 2.0], [0.0, 0.0, -2.0]],
            faces=[],
        )
        src = make_sphere_mesh_approx()
        result = retopo_snap(src, cage)
        # Top vertex: was at (0,0,2), octahedron apex at (0,0,1) → should be closer to (0,0,1)
        v0 = result.vertices[0]
        dist_before = math.sqrt(0 + 0 + (2.0 - 1.0)**2)  # distance from (0,0,2) to apex
        dist_after = math.sqrt(v0[0]**2 + v0[1]**2 + (v0[2] - 1.0)**2)
        assert dist_after < dist_before, f"Snap should move vertex closer to surface"

    def test_snap_with_quad_source_triangulates(self):
        """Source mesh with quads should be triangulated and snap should work."""
        verts = [[0, 0, 0], [2, 0, 0], [2, 2, 0], [0, 2, 0]]
        faces = [[0, 1, 2, 3]]  # quad
        src = {"vertices": verts, "faces": faces}
        cage = SubDCage(
            vertices=[[1.0, 1.0, 0.5]],
            faces=[],
        )
        result = retopo_snap(src, cage)
        v = result.vertices[0]
        assert abs(v[2]) < 0.01, f"Should snap to z=0 plane, got z={v[2]}"
