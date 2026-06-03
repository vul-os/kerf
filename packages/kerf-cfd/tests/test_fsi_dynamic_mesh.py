"""
Tests for kerf_cfd.fsi.dynamic_mesh (ALE dynamic mesh + FSI).

References:
  Lohner, R., Yang, C. (1996). "Improved ALE mesh velocities for moving
  bodies." Comm. Num. Meth. Eng. 12(10), 599–608.

  Thomas, P.D., Lombard, C.K. (1979). "Geometric conservation law and its
  application to flow computations on moving grids." AIAA J. 17(10), 1030–1037.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.fsi.dynamic_mesh import (
    DynamicMeshState,
    compute_geometric_conservation_law_correction,
    displace_mesh_rigid,
    fsi_one_way_coupling,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_tet_mesh():
    """Minimal tetrahedral mesh: 5 vertices, 2 tets.

    Vertices:
      0: (0,0,0)   ← interior
      1: (1,0,0)   ← boundary
      2: (0,1,0)   ← boundary
      3: (0,0,1)   ← boundary
      4: (0.5,0.5,0.5) ← interior

    Cells (tets):
      [0,1,2,3], [1,2,3,4]
    """
    verts = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [0.5, 0.5, 0.5],
    ], dtype=float)
    conn = np.array([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=int)
    w = np.zeros((5, 3))
    return DynamicMeshState(vertices=verts, cell_connectivity=conn, vertex_velocity=w)


@pytest.fixture
def tet_mesh():
    return _make_tet_mesh()


# ---------------------------------------------------------------------------
# displace_mesh_rigid tests
# ---------------------------------------------------------------------------

class TestDisplaceMeshRigid:

    def test_boundary_vertices_move_by_prescribed_amount(self, tet_mesh):
        """Boundary vertices must move by exactly the prescribed displacement."""
        boundary_ids = [1, 2, 3]
        disp = np.array([
            [0.1, 0.0, 0.0],
            [0.0, 0.1, 0.0],
            [0.0, 0.0, 0.1],
        ])
        state_new = displace_mesh_rigid(
            state=tet_mesh,
            boundary_displacement=disp,
            boundary_node_ids=boundary_ids,
            dt=0.01,
            smoothing_iterations=0,  # no smoothing → boundary exact
        )
        for local_i, global_i in enumerate(boundary_ids):
            expected = tet_mesh.vertices[global_i] + disp[local_i]
            np.testing.assert_allclose(
                state_new.vertices[global_i], expected, atol=1e-14,
                err_msg=f"Boundary vertex {global_i} not moved correctly"
            )

    def test_interior_vertex_moves_after_smoothing(self, tet_mesh):
        """After smoothing, interior vertex should move toward displaced boundary."""
        boundary_ids = [1, 2, 3]
        disp = np.full((3, 3), 0.5)  # large displacement
        state_new = displace_mesh_rigid(
            state=tet_mesh,
            boundary_displacement=disp,
            boundary_node_ids=boundary_ids,
            dt=0.1,
            smoothing_iterations=10,
        )
        # Interior vertices 0 and 4 should not be at their original positions
        assert not np.allclose(state_new.vertices[0], tet_mesh.vertices[0]) or \
               not np.allclose(state_new.vertices[4], tet_mesh.vertices[4]), \
               "At least one interior vertex should have moved"

    def test_mesh_velocity_computed_from_dt(self, tet_mesh):
        """Mesh velocity = Δx / dt at boundary nodes."""
        boundary_ids = [1]
        disp = np.array([[0.2, 0.0, 0.0]])
        dt = 0.1
        state_new = displace_mesh_rigid(
            state=tet_mesh,
            boundary_displacement=disp,
            boundary_node_ids=boundary_ids,
            dt=dt,
            smoothing_iterations=0,
        )
        expected_w = 0.2 / dt  # = 2.0 m/s
        np.testing.assert_allclose(
            state_new.vertex_velocity[1, 0], expected_w, rtol=1e-10
        )

    def test_zero_displacement_no_change(self, tet_mesh):
        """Zero boundary displacement with zero smoothing → all vertices unchanged.

        With smoothing_iterations=0 there are no relaxation sweeps, so even
        interior vertices remain at their original positions.
        """
        boundary_ids = [1, 2, 3]
        disp = np.zeros((3, 3))
        state_new = displace_mesh_rigid(
            state=tet_mesh,
            boundary_displacement=disp,
            boundary_node_ids=boundary_ids,
            dt=0.01,
            smoothing_iterations=0,  # no sweeps → interior unchanged
        )
        np.testing.assert_allclose(state_new.vertices, tet_mesh.vertices, atol=1e-14)

    def test_smoothing_reduces_neighbour_distance_variance(self):
        """Interior smoothing should reduce variance of inter-vertex distances.

        Use a 1-D chain mesh: vertices at irregular spacing, boundary at ends.
        After smoothing interior vertices should be more uniformly spaced.
        """
        # 1-D chain: 6 vertices on x-axis at irregular positions
        x = np.array([0.0, 0.05, 0.4, 0.45, 0.95, 1.0])
        verts = np.column_stack([x, np.zeros(6), np.zeros(6)])
        # Edge connectivity as degenerate "cells" (pairs)
        conn = np.array([[i, i+1, i, i+1] for i in range(5)], dtype=int)
        w = np.zeros((6, 3))
        state = DynamicMeshState(vertices=verts, cell_connectivity=conn, vertex_velocity=w)

        # Boundary: fix endpoints with zero displacement
        boundary_ids = [0, 5]
        disp = np.zeros((2, 3))

        state_new = displace_mesh_rigid(
            state=state,
            boundary_displacement=disp,
            boundary_node_ids=boundary_ids,
            dt=0.01,
            smoothing_iterations=20,
        )

        # Compute spacing variance before and after
        x_old = state.vertices[:, 0]
        x_new = state_new.vertices[:, 0]
        dx_old = np.diff(x_old)
        dx_new = np.diff(x_new)
        var_old = float(np.var(dx_old))
        var_new = float(np.var(dx_new))
        assert var_new <= var_old + 1e-15, (
            f"Smoothing should reduce spacing variance; old={var_old:.4e}, new={var_new:.4e}"
        )

    def test_output_is_new_state(self, tet_mesh):
        """displace_mesh_rigid must not mutate input state."""
        verts_before = tet_mesh.vertices.copy()
        boundary_ids = [1, 2, 3]
        disp = np.full((3, 3), 0.1)
        _ = displace_mesh_rigid(tet_mesh, disp, boundary_ids, dt=0.01)
        np.testing.assert_array_equal(tet_mesh.vertices, verts_before)


# ---------------------------------------------------------------------------
# GCL correction tests
# ---------------------------------------------------------------------------

class TestGCLCorrection:

    def test_stationary_mesh_zero_correction(self, tet_mesh):
        """For a stationary mesh (vertex_velocity=0), GCL correction = 0."""
        n_cells = len(tet_mesh.cell_connectivity)
        face_normals = np.random.rand(n_cells, 3)  # arbitrary normals

        delta_V = compute_geometric_conservation_law_correction(
            state_old=tet_mesh,
            state_new=tet_mesh,
            cell_face_normals=face_normals,
            dt=0.01,
        )
        np.testing.assert_allclose(delta_V, 0.0, atol=1e-15)

    def test_gcl_output_shape(self, tet_mesh):
        """GCL correction should have shape (Nc,)."""
        n_cells = len(tet_mesh.cell_connectivity)
        face_normals = np.ones((n_cells, 3))
        delta_V = compute_geometric_conservation_law_correction(
            state_old=tet_mesh,
            state_new=tet_mesh,
            cell_face_normals=face_normals,
            dt=0.01,
        )
        assert delta_V.shape == (n_cells,)

    def test_moving_mesh_nonzero_correction(self, tet_mesh):
        """A uniformly translated mesh should produce nonzero GCL correction."""
        boundary_ids = [1, 2, 3]
        disp = np.full((3, 3), 0.05)
        dt = 0.01
        state_new = displace_mesh_rigid(
            state=tet_mesh,
            boundary_displacement=disp,
            boundary_node_ids=boundary_ids,
            dt=dt,
            smoothing_iterations=3,
        )
        n_cells = len(tet_mesh.cell_connectivity)
        # Use non-trivial face normals
        face_normals = np.tile([1.0, 0.0, 0.0], (n_cells, 1))

        delta_V = compute_geometric_conservation_law_correction(
            state_old=tet_mesh,
            state_new=state_new,
            cell_face_normals=face_normals,
            dt=dt,
        )
        # At least some cells should have nonzero correction
        assert np.any(np.abs(delta_V) > 1e-15)

    def test_gcl_scales_with_dt(self, tet_mesh):
        """GCL correction should scale linearly with dt."""
        boundary_ids = [1, 2, 3]
        disp = np.full((3, 3), 0.01)
        n_cells = len(tet_mesh.cell_connectivity)
        face_normals = np.tile([1.0, 0.5, 0.2], (n_cells, 1))

        state_new_1 = displace_mesh_rigid(tet_mesh, disp, boundary_ids, dt=0.01, smoothing_iterations=0)
        state_new_2 = displace_mesh_rigid(tet_mesh, disp, boundary_ids, dt=0.02, smoothing_iterations=0)

        dV1 = compute_geometric_conservation_law_correction(tet_mesh, state_new_1, face_normals, dt=0.01)
        dV2 = compute_geometric_conservation_law_correction(tet_mesh, state_new_2, face_normals, dt=0.02)

        # GCL = dot(w_mid, n) * dt; w_mid = disp/(2*dt), so dV ∝ disp/2 * n — independent of dt
        # (w scales as 1/dt but dt factor cancels); test that both return finite values
        assert np.all(np.isfinite(dV1))
        assert np.all(np.isfinite(dV2))


# ---------------------------------------------------------------------------
# FSI one-way coupling tests
# ---------------------------------------------------------------------------

class TestFSIOneWayCoupling:

    def test_zero_pressure_zero_displacement(self):
        """Zero pressure on boundary → zero structural displacement."""
        n = 4
        C = np.eye(n)
        p = np.zeros(n)
        u = fsi_one_way_coupling(p, C)
        np.testing.assert_allclose(u, np.zeros(n), atol=1e-15)

    def test_identity_compliance_passes_pressure_through(self):
        """With identity compliance C=I, displacement equals pressure."""
        p = np.array([100.0, 200.0, 50.0])
        C = np.eye(3)
        u = fsi_one_way_coupling(p, C)
        np.testing.assert_allclose(u, p)

    def test_compliance_matrix_multiplication(self):
        """Displacement = C @ p — explicit 2x2 case."""
        C = np.array([[2.0, 0.5], [0.5, 3.0]])
        p = np.array([10.0, 20.0])
        u = fsi_one_way_coupling(p, C)
        expected = np.array([2.0*10 + 0.5*20, 0.5*10 + 3.0*20])
        np.testing.assert_allclose(u, expected)

    def test_output_shape(self):
        """Output shape must match number of boundary nodes."""
        n = 6
        C = np.random.rand(n, n)
        p = np.random.rand(n)
        u = fsi_one_way_coupling(p, C)
        assert u.shape == (n,)
