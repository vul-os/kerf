"""Tests for GK-P20: subd_poke — centroid fan."""
from __future__ import annotations
import pytest
from kerf_cad_core.geom.subd_authoring import SubDCage, subd_poke


def make_cube_cage() -> SubDCage:
    verts = [
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1,  1], [1, -1,  1], [1, 1,  1], [-1, 1,  1],
    ]
    faces = [[0,1,2,3],[4,5,6,7],[0,1,5,4],[2,3,7,6],[0,3,7,4],[1,2,6,5]]
    return SubDCage(vertices=[list(v) for v in verts], faces=faces)


class TestSubdPoke:
    def test_poke_quad_adds_centroid(self):
        cage = make_cube_cage()
        result = subd_poke(cage, 0)
        # Original 8 verts + 1 centroid
        assert len(result.vertices) == 9

    def test_poke_quad_replaces_with_triangles(self):
        cage = make_cube_cage()
        result = subd_poke(cage, 0)
        # face 0 (quad) → 4 triangles; 5 other faces unchanged
        # total: 5 + 4 = 9 faces
        assert len(result.faces) == 9

    def test_poke_centroid_position(self):
        cage = make_cube_cage()
        face0 = cage.faces[0]  # [0,1,2,3]
        cx = sum(cage.vertices[vi][0] for vi in face0) / 4
        cy = sum(cage.vertices[vi][1] for vi in face0) / 4
        cz = sum(cage.vertices[vi][2] for vi in face0) / 4
        result = subd_poke(cage, 0)
        new_v = result.vertices[8]  # the new centroid vertex
        assert abs(new_v[0] - cx) < 1e-10
        assert abs(new_v[1] - cy) < 1e-10
        assert abs(new_v[2] - cz) < 1e-10

    def test_poke_triangles_all_share_centroid(self):
        cage = make_cube_cage()
        result = subd_poke(cage, 0)
        centroid_vi = 8
        poked_faces = result.faces[:4]  # first 4 faces are the new triangles
        for f in poked_faces:
            assert centroid_vi in f, f"Centroid not in poked face: {f}"
            assert len(f) == 3, f"Poked face should be triangle, got {len(f)}-gon"

    def test_poke_other_faces_unchanged(self):
        cage = make_cube_cage()
        result = subd_poke(cage, 0)
        # faces 1-5 of original → last 5 faces of result
        orig_other = [list(f) for f in cage.faces[1:]]
        result_other = [list(f) for f in result.faces[4:]]
        assert orig_other == result_other

    def test_poke_invalid_face_id_returns_copy(self):
        cage = make_cube_cage()
        result = subd_poke(cage, 99)
        assert result.vertices == cage.vertices
        assert result.faces == cage.faces

    def test_poke_ngon(self):
        """Poke an n-gon creates n triangles."""
        cage = SubDCage(
            vertices=[[0,0,0],[1,0,0],[1.5,1,0],[0.5,1.5,0],[-0.5,1,0]],
            faces=[[0,1,2,3,4]],
        )
        result = subd_poke(cage, 0)
        assert len(result.vertices) == 6  # 5 + centroid
        assert len(result.faces) == 5     # 5 triangles
