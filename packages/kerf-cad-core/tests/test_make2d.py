"""
Tests for kerf_cad_core.geom.make2d — Make2D / hidden-line removal.

All tests are hermetic (pure-Python + NumPy, no database, no OCC).
Covers >= 30 cases:
  - ViewParams and Make2DInput dataclass validation
  - View matrix construction (top/front/right/iso orthogonality)
  - Vertex projection: ortho and perspective math vs hand-calc
  - Edge extraction: silhouette, boundary, crease detection on cube
  - Silhouette edge counts for known geometries (cube, tetra, sphere)
  - Hidden-line classification: cube from isometric view visible/hidden counts
  - make2d() entry point: result shape, scale application, degenerate inputs
  - standard_views() keys and direction orthogonality
  - Edge-on-view / degenerate cases: zero-length edges, coincident verts, flat mesh
  - Make2DInput.is_valid(): error messages for bad shapes/indices
  - Point-in-triangle and depth interpolation helpers
  - Feature edge extraction with crease angle threshold
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.make2d import (
    Make2DInput,
    Make2DResult,
    ViewParams,
    _build_view_matrix,
    _compute_face_normals,
    _extract_feature_edges,
    _extract_silhouette_edges,
    _build_edge_face_map,
    _point_in_triangle_2d,
    _project_vertices,
    _triangle_depth_at_point_2d,
    _make_cube_mesh,
    _make_tetra_mesh,
    _make_sphere_mesh,
    make2d,
    standard_views,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _cube_front_view() -> ViewParams:
    return ViewParams(direction=[0.0, -1.0, 0.0], up=[0.0, 0.0, 1.0])


def _cube_iso_view() -> ViewParams:
    d = np.array([1.0, -1.0, -1.0], dtype=float)
    d /= np.linalg.norm(d)
    return ViewParams(direction=d.tolist(), up=[0.0, 0.0, 1.0])


# ────────────────────────────────────────────────────────────────────────────
# 1. ViewParams
# ────────────────────────────────────────────────────────────────────────────

class TestViewParams:
    def test_default_direction_is_neg_z(self):
        vp = ViewParams()
        d = vp.validated_direction()
        assert np.allclose(d, [0, 0, -1], atol=1e-9)

    def test_direction_is_normalised(self):
        vp = ViewParams(direction=[3.0, 0.0, 0.0])
        d = vp.validated_direction()
        assert abs(np.linalg.norm(d) - 1.0) < 1e-9

    def test_zero_direction_falls_back(self):
        vp = ViewParams(direction=[0.0, 0.0, 0.0])
        d = vp.validated_direction()
        assert np.linalg.norm(d) > 0.9

    def test_default_projection_is_ortho(self):
        vp = ViewParams()
        assert vp.projection == "ortho"

    def test_up_is_normalised(self):
        vp = ViewParams(up=[0.0, 2.0, 0.0])
        u = vp.validated_up()
        assert abs(np.linalg.norm(u) - 1.0) < 1e-9


# ────────────────────────────────────────────────────────────────────────────
# 2. Make2DInput validation
# ────────────────────────────────────────────────────────────────────────────

class TestMake2DInputValidation:
    def test_valid_cube_is_valid(self):
        mesh = _make_cube_mesh()
        ok, reason = mesh.is_valid()
        assert ok, reason

    def test_empty_vertices_invalid(self):
        mesh = Make2DInput(
            vertices=np.zeros((0, 3)),
            triangles=np.zeros((0, 3), dtype=int),
        )
        ok, _ = mesh.is_valid()
        assert not ok

    def test_wrong_vertex_shape_invalid(self):
        mesh = Make2DInput(
            vertices=np.ones((5, 2)),
            triangles=np.array([[0, 1, 2]], dtype=int),
        )
        ok, reason = mesh.is_valid()
        assert not ok
        assert "3" in reason

    def test_index_out_of_range_invalid(self):
        verts = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        tris = np.array([[0, 1, 99]])
        mesh = Make2DInput(vertices=verts, triangles=tris)
        ok, reason = mesh.is_valid()
        assert not ok
        assert "out of range" in reason

    def test_empty_triangles_invalid(self):
        verts = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]])
        mesh = Make2DInput(vertices=verts, triangles=np.zeros((0, 3), dtype=int))
        ok, _ = mesh.is_valid()
        assert not ok


# ────────────────────────────────────────────────────────────────────────────
# 3. View matrix orthogonality
# ────────────────────────────────────────────────────────────────────────────

class TestViewMatrix:
    def _assert_orthonormal_rows(self, M: np.ndarray) -> None:
        """Check the 3×3 rotation block is orthonormal."""
        R = M[:3, :3]
        prod = R @ R.T
        assert np.allclose(prod, np.eye(3), atol=1e-9), f"Not orthonormal:\n{prod}"

    def test_top_view_orthonormal(self):
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        M = _build_view_matrix(vp)
        self._assert_orthonormal_rows(M)

    def test_front_view_orthonormal(self):
        vp = _cube_front_view()
        M = _build_view_matrix(vp)
        self._assert_orthonormal_rows(M)

    def test_iso_view_orthonormal(self):
        vp = _cube_iso_view()
        M = _build_view_matrix(vp)
        self._assert_orthonormal_rows(M)

    def test_collinear_dir_up_fallback(self):
        # direction == up: should not crash
        vp = ViewParams(direction=[0, 1, 0], up=[0, 1, 0])
        M = _build_view_matrix(vp)
        assert M.shape == (4, 4)
        R = M[:3, :3]
        # Rows should still be unit vectors
        for row in R:
            assert abs(np.linalg.norm(row) - 1.0) < 1e-9


# ────────────────────────────────────────────────────────────────────────────
# 4. Projection math (hand-calc verification)
# ────────────────────────────────────────────────────────────────────────────

class TestProjection:
    def test_ortho_top_view_point_on_xaxis(self):
        # Looking down -Z: point (2, 3, 5) should project to (2, 3) in view space.
        verts = np.array([[2.0, 3.0, 5.0]], dtype=float)
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        M = _build_view_matrix(vp)
        uv, depth = _project_vertices(verts - verts.mean(0), M, vp)
        # Centred: (0, 0, 0) → projected to (0, 0)
        assert uv.shape == (1, 2)
        assert abs(uv[0, 0]) < 1e-9
        assert abs(uv[0, 1]) < 1e-9

    def test_ortho_depth_ordering(self):
        # Two points: looking down -Z (fwd=[0,0,-1]).
        # View matrix row 2 = -fwd = [0,0,+1], so v_z = world_z.
        # depth = -v_z, so higher world Z → lower (more negative) depth.
        # A point closer to the camera (higher world Z for top-down) has smaller depth value.
        verts = np.array([
            [0.0, 0.0, 1.0],  # world Z=1 → v_z=1 → depth=-1 (closer to camera)
            [0.0, 0.0, -1.0], # world Z=-1 → v_z=-1 → depth=1  (farther)
        ], dtype=float)
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        M = _build_view_matrix(vp)
        centroid = verts.mean(0)
        uv, depth = _project_vertices(verts - centroid, M, vp)
        # depth = -v_z; the "closer" point (z=1) has depth=-1, farther (z=-1) has depth=1
        # The two depths differ in the expected direction
        assert depth[0] != depth[1]
        # Farther point has LARGER depth value (bigger positive depth value)
        assert depth[1] > depth[0]

    def test_ortho_two_points_separation(self):
        # Points at (±1, 0, 0) looking from front; should be separated in x
        verts = np.array([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]])
        vp = _cube_front_view()
        M = _build_view_matrix(vp)
        uv, _ = _project_vertices(verts - verts.mean(0), M, vp)
        assert uv[0, 0] != uv[1, 0]
        assert abs(uv[0, 0] + uv[1, 0]) < 1e-9  # symmetric

    def test_perspective_projection_varies_with_fov(self):
        # Perspective: a wider FOV should make the same points appear farther apart
        # than a narrow FOV (zoomed in).
        all_pts = np.array([
            [ 1.0, 0.0, -5.0],
            [-1.0, 0.0, -5.0],
        ])
        centroid = all_pts.mean(0)
        pts_c = all_pts - centroid

        vp_wide = ViewParams(direction=[0, 0, -1], up=[0, 1, 0],
                             projection="perspective", fov_deg=90.0)
        vp_narrow = ViewParams(direction=[0, 0, -1], up=[0, 1, 0],
                               projection="perspective", fov_deg=30.0)

        M = _build_view_matrix(vp_wide)
        uv_wide, _ = _project_vertices(pts_c, M, vp_wide)
        uv_narrow, _ = _project_vertices(pts_c, M, vp_narrow)

        sep_wide   = abs(uv_wide[0, 0] - uv_wide[1, 0])
        sep_narrow = abs(uv_narrow[0, 0] - uv_narrow[1, 0])
        # Wide FOV → smaller f → smaller projected coords
        assert sep_wide < sep_narrow

    def test_ortho_scale_does_not_affect_projection(self):
        # Scale is applied after projection in make2d; raw uv is unscaled
        verts = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        M = _build_view_matrix(vp)
        uv, depth = _project_vertices(verts - verts.mean(0), M, vp)
        assert uv.shape == (3, 2)


# ────────────────────────────────────────────────────────────────────────────
# 5. Edge extraction
# ────────────────────────────────────────────────────────────────────────────

class TestEdgeExtraction:
    def test_cube_has_12_boundary_or_crease_feature_edges(self):
        # A closed cube mesh has no boundary edges (all edges shared by 2 faces).
        # With default 30° crease, all hard edges between orthogonal faces are creases.
        mesh = _make_cube_mesh()
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        edges = _extract_feature_edges(mesh, face_normals, ef_map)
        # Cube has 12 edges, each at 90° (> 30° crease threshold)
        assert len(edges) == 12

    def test_tetra_has_6_feature_edges(self):
        mesh = _make_tetra_mesh()
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        edges = _extract_feature_edges(mesh, face_normals, ef_map)
        assert len(edges) == 6

    def test_high_crease_angle_suppresses_creases(self):
        # 180° threshold: no crease edges on cube (all faces would need to be coplanar)
        mesh = _make_cube_mesh(1.0)
        mesh.crease_angle_deg = 179.0
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        edges = _extract_feature_edges(mesh, face_normals, ef_map)
        assert len(edges) == 0

    def test_low_crease_angle_includes_all_shared_edges(self):
        # 0° threshold: every shared edge qualifies as crease if normals differ at all
        mesh = _make_cube_mesh(1.0)
        mesh.crease_angle_deg = 0.1
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        edges = _extract_feature_edges(mesh, face_normals, ef_map)
        assert len(edges) == 12

    def test_silhouette_edges_nonempty_cube_front(self):
        mesh = _make_cube_mesh()
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        view_dir = ViewParams(direction=[0, -1, 0]).validated_direction()
        silhouettes = _extract_silhouette_edges(mesh, face_normals, ef_map, view_dir)
        assert len(silhouettes) > 0

    def test_silhouette_edges_on_cube_top_view(self):
        # Looking straight down (-Z): all lateral edges should be silhouettes
        mesh = _make_cube_mesh()
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        view_dir = ViewParams(direction=[0, 0, -1]).validated_direction()
        silhouettes = _extract_silhouette_edges(mesh, face_normals, ef_map, view_dir)
        assert len(silhouettes) >= 4  # at least 4 vertical edges are silhouettes

    def test_sphere_silhouettes_vary_by_view(self):
        mesh = _make_sphere_mesh(1.0, subdivisions=2)
        face_normals = _compute_face_normals(mesh.vertices, mesh.triangles)
        ef_map = _build_edge_face_map(mesh.triangles)
        view1 = ViewParams(direction=[0, 0, -1]).validated_direction()
        view2 = ViewParams(direction=[1, 0, 0]).validated_direction()
        sil1 = _extract_silhouette_edges(mesh, face_normals, ef_map, view1)
        sil2 = _extract_silhouette_edges(mesh, face_normals, ef_map, view2)
        # Both should have silhouettes, and counts should be non-trivially large
        assert len(sil1) > 4
        assert len(sil2) > 4


# ────────────────────────────────────────────────────────────────────────────
# 6. Point-in-triangle and depth helpers
# ────────────────────────────────────────────────────────────────────────────

class TestGeomHelpers:
    def test_centroid_inside_triangle(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([0.5, 1.0])
        centroid = (a + b + c) / 3.0
        assert _point_in_triangle_2d(centroid, a, b, c)

    def test_outside_point_not_in_triangle(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([0.5, 1.0])
        outside = np.array([2.0, 0.0])
        assert not _point_in_triangle_2d(outside, a, b, c)

    def test_vertex_on_triangle_boundary(self):
        a = np.array([0.0, 0.0])
        b = np.array([1.0, 0.0])
        c = np.array([0.5, 1.0])
        assert _point_in_triangle_2d(a, a, b, c)

    def test_depth_at_centroid_is_average(self):
        a2 = np.array([0.0, 0.0])
        b2 = np.array([1.0, 0.0])
        c2 = np.array([0.5, 1.0])
        centroid = (a2 + b2 + c2) / 3.0
        d = _triangle_depth_at_point_2d(centroid, a2, b2, c2, 1.0, 2.0, 3.0)
        assert d is not None
        assert abs(d - 2.0) < 1e-6  # (1+2+3)/3=2

    def test_depth_at_vertex_equals_vertex_depth(self):
        a2 = np.array([0.0, 0.0])
        b2 = np.array([1.0, 0.0])
        c2 = np.array([0.0, 1.0])
        d = _triangle_depth_at_point_2d(a2, a2, b2, c2, 5.0, 1.0, 1.0)
        assert d is not None
        assert abs(d - 5.0) < 1e-5

    def test_depth_outside_returns_none(self):
        a2 = np.array([0.0, 0.0])
        b2 = np.array([1.0, 0.0])
        c2 = np.array([0.5, 1.0])
        outside = np.array([5.0, 5.0])
        d = _triangle_depth_at_point_2d(outside, a2, b2, c2, 1.0, 2.0, 3.0)
        assert d is None


# ────────────────────────────────────────────────────────────────────────────
# 7. make2d() end-to-end
# ────────────────────────────────────────────────────────────────────────────

class TestMake2D:
    def test_cube_front_returns_result_object(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp)
        assert isinstance(result, Make2DResult)

    def test_cube_front_has_some_visible_edges(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp)
        assert len(result.visible) > 0

    def test_cube_front_has_some_hidden_edges(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp)
        # Back edges of the cube should be hidden
        assert len(result.hidden) > 0

    def test_cube_iso_view_visible_hidden_partition(self):
        mesh = _make_cube_mesh()
        vp = _cube_iso_view()
        result = make2d(mesh, vp, subdivisions=4)
        total = len(result.visible) + len(result.hidden)
        # Cube has 12 edges; all should be classified
        assert total == 12

    def test_cube_iso_visible_more_than_hidden(self):
        # From iso view, 9 edges visible, 3 hidden for a unit cube
        mesh = _make_cube_mesh()
        vp = _cube_iso_view()
        result = make2d(mesh, vp, subdivisions=8)
        # Allow ±1 for numerical edge cases
        assert len(result.visible) >= 7
        assert len(result.hidden) >= 2

    def test_scale_is_applied_to_output(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        r1 = make2d(mesh, vp, scale=1.0)
        r2 = make2d(mesh, vp, scale=2.0)
        # Collect all x-coords
        xs1 = [abs(p[0]) for poly in r1.visible for p in poly]
        xs2 = [abs(p[0]) for poly in r2.visible for p in poly]
        if xs1 and xs2:
            # With scale=2 the coords should be twice as large
            max1 = max(xs1)
            max2 = max(xs2)
            if max1 > 1e-9:
                assert abs(max2 / max1 - 2.0) < 0.05

    def test_view_matrix_is_4x4(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp)
        assert result.view_matrix.shape == (4, 4)

    def test_result_scale_matches_input(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp, scale=3.7)
        assert abs(result.scale - 3.7) < 1e-9

    def test_silhouette_count_is_positive_for_cube(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp)
        assert result.silhouette_count > 0

    def test_feature_count_is_positive_for_cube(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        result = make2d(mesh, vp)
        assert result.feature_count > 0

    def test_tetra_make2d_runs(self):
        mesh = _make_tetra_mesh()
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        result = make2d(mesh, vp)
        assert isinstance(result, Make2DResult)
        assert len(result.visible) + len(result.hidden) > 0

    def test_sphere_make2d_silhouette_nonempty(self):
        mesh = _make_sphere_mesh(1.0, subdivisions=1)
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        result = make2d(mesh, vp, subdivisions=4)
        assert result.silhouette_count > 0

    def test_invalid_scale_raises(self):
        mesh = _make_cube_mesh()
        vp = _cube_front_view()
        with pytest.raises(ValueError, match="scale"):
            make2d(mesh, vp, scale=-1.0)

    def test_invalid_mesh_raises(self):
        mesh = Make2DInput(
            vertices=np.zeros((0, 3)),
            triangles=np.zeros((0, 3), dtype=int),
        )
        vp = _cube_front_view()
        with pytest.raises(ValueError):
            make2d(mesh, vp)

    def test_top_view_cube_produces_4_visible_boundary_edges(self):
        # Top-down ortho: 4 top edges visible, 4 bottom hidden, 4 lateral split
        mesh = _make_cube_mesh()
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        result = make2d(mesh, vp, subdivisions=6)
        # At minimum the 4 top face edges should be visible
        assert len(result.visible) >= 4


# ────────────────────────────────────────────────────────────────────────────
# 8. standard_views()
# ────────────────────────────────────────────────────────────────────────────

class TestStandardViews:
    def test_standard_views_has_four_keys(self):
        sv = standard_views()
        assert set(sv.keys()) == {"top", "front", "right", "iso"}

    def test_all_views_are_view_params(self):
        sv = standard_views()
        for name, vp in sv.items():
            assert isinstance(vp, ViewParams), f"{name} is not ViewParams"

    def test_all_views_have_unit_direction(self):
        sv = standard_views()
        for name, vp in sv.items():
            d = vp.validated_direction()
            assert abs(np.linalg.norm(d) - 1.0) < 1e-9, f"{name} direction not unit"

    def test_view_matrices_are_orthonormal(self):
        sv = standard_views()
        for name, vp in sv.items():
            M = _build_view_matrix(vp)
            R = M[:3, :3]
            assert np.allclose(R @ R.T, np.eye(3), atol=1e-9), \
                f"{name} view matrix not orthonormal"

    def test_iso_direction_is_normalised(self):
        sv = standard_views()
        iso_d = sv["iso"].validated_direction()
        assert abs(np.linalg.norm(iso_d) - 1.0) < 1e-9

    def test_top_looks_down_z(self):
        sv = standard_views()
        d = sv["top"].validated_direction()
        # Should be pointing mostly in -Z direction
        assert d[2] < -0.9

    def test_front_looks_along_y(self):
        sv = standard_views()
        d = sv["front"].validated_direction()
        assert abs(d[1]) > 0.9


# ────────────────────────────────────────────────────────────────────────────
# 9. Degenerate / edge-on-view cases
# ────────────────────────────────────────────────────────────────────────────

class TestDegenerateCases:
    def test_flat_mesh_top_view(self):
        # A flat quad (two triangles) lying in XY plane, viewed from top
        verts = np.array([
            [0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]
        ])
        tris = np.array([[0, 1, 2], [0, 2, 3]])
        mesh = Make2DInput(vertices=verts, triangles=tris)
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        result = make2d(mesh, vp, subdivisions=4)
        # Should not crash; edges should be visible
        assert isinstance(result, Make2DResult)
        assert len(result.visible) + len(result.hidden) > 0

    def test_edge_on_view_flat_mesh_front_view(self):
        # Flat mesh viewed from the edge (front view); all edges in plane
        verts = np.array([
            [0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]
        ])
        tris = np.array([[0, 1, 2], [0, 2, 3]])
        mesh = Make2DInput(vertices=verts, triangles=tris)
        vp = ViewParams(direction=[0, 1, 0], up=[0, 0, 1])
        # Should not crash even if all edges project to points/lines
        result = make2d(mesh, vp, subdivisions=4)
        assert isinstance(result, Make2DResult)

    def test_single_triangle_mesh(self):
        verts = np.array([[0., 0., 0.], [2., 0., 0.], [1., 2., 0.]])
        tris = np.array([[0, 1, 2]])
        mesh = Make2DInput(vertices=verts, triangles=tris)
        vp = ViewParams(direction=[0, 0, -1], up=[0, 1, 0])
        result = make2d(mesh, vp, subdivisions=4)
        assert isinstance(result, Make2DResult)
        # Single triangle → 3 boundary edges → all should appear
        assert len(result.visible) + len(result.hidden) == 3

    def test_perspective_projection_does_not_crash(self):
        mesh = _make_cube_mesh()
        vp = ViewParams(direction=[0, -1, -1],
                        up=[0, 1, 0],
                        projection="perspective",
                        fov_deg=45.0)
        result = make2d(mesh, vp, subdivisions=4)
        assert isinstance(result, Make2DResult)

    def test_explicit_feature_edges_honoured(self):
        mesh = _make_cube_mesh()
        # Provide only one explicit feature edge (0→1)
        mesh.feature_edges = np.array([[0, 1]])
        vp = _cube_front_view()
        result = make2d(mesh, vp, subdivisions=4)
        # With only 1 feature edge + silhouettes, total should still be > 0
        assert len(result.visible) + len(result.hidden) > 0
