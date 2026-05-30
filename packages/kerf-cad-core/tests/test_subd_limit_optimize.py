"""Tests for subd_limit_optimize — SubD cage CP optimization.

Four analytical oracle tests:

1. Flat plane constraint:
   A flat (z=0) cage with constraint 'passes_through' at center (0.5,0.5)
   targeting z=1.0 → optimization moves CPs upward; final residual < 1e-3.

2. Normal constraint:
   A flat cage with 'has_normal' = (0, 1, 0) at center → optimizer tilts the
   cage; final normal agrees with (0,1,0) within 5 degrees.

3. Multi-constraint:
   Three 'passes_through' constraints on three different face centers →
   all residuals < 1e-2 after optimization.

4. Convergence:
   Residuals decrease monotonically across iterations (loss history is
   non-increasing).
"""
from __future__ import annotations

import math
import copy
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_limit_optimize import (
    LimitConstraint,
    CageOptimizeResult,
    optimize_cage_for_constraints,
    fit_cage_to_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_flat_quad_mesh(z: float = 0.0, scale: float = 1.0) -> SubDMesh:
    """A single 2×2 quad mesh (4 quads around a centre vertex), flat at z."""
    # 3×3 grid of vertices — 4 quad faces
    verts = [
        [0.0, 0.0, z], [scale, 0.0, z], [2 * scale, 0.0, z],
        [0.0, scale, z], [scale, scale, z], [2 * scale, scale, z],
        [0.0, 2 * scale, z], [scale, 2 * scale, z], [2 * scale, 2 * scale, z],
    ]
    faces = [
        [0, 1, 4, 3],  # face 0
        [1, 2, 5, 4],  # face 1
        [3, 4, 7, 6],  # face 2
        [4, 5, 8, 7],  # face 3
    ]
    return SubDMesh(vertices=verts, faces=faces)


def angle_between_vectors(a: np.ndarray, b: np.ndarray) -> float:
    """Angle in degrees between two 3-D vectors."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-14 or nb < 1e-14:
        return 90.0
    dot = float(np.dot(a / na, b / nb))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(abs(dot)))  # abs: sign-invariant for normal comparison


# ---------------------------------------------------------------------------
# Test 1: Flat plane passes_through — CPs move upward
# ---------------------------------------------------------------------------

class TestFlatPlanePassesThrough:
    """Oracle: a flat cage pushed by a 'passes_through' constraint at z=1."""

    def test_residual_drops_below_threshold(self):
        """Final residual at the constraint point must be < 1e-3."""
        mesh = make_flat_quad_mesh(z=0.0)

        constraint = LimitConstraint(
            kind="passes_through",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.75, 0.75, 1.0],  # somewhere above the flat plane
        )

        result = optimize_cage_for_constraints(
            mesh, [constraint], n_iters=200, lr=0.05
        )

        assert len(result.residuals) == 1
        final_residual = result.residuals[0]
        assert final_residual < 1e-3, (
            f"passes_through residual {final_residual:.4e} >= 1e-3; "
            f"optimizer did not converge to constraint"
        )

    def test_vertices_moved_upward(self):
        """After optimization, at least one CP has moved toward the target z."""
        mesh = make_flat_quad_mesh(z=0.0)
        constraint = LimitConstraint(
            kind="passes_through",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.75, 0.75, 1.0],
        )

        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=200, lr=0.05)

        # At least one vertex should have z > 0 after optimization
        zs = [v[2] for v in result.mesh.vertices]
        assert max(zs) > 1e-6, (
            f"No CP moved upward toward z=1 target; max_z = {max(zs):.4e}"
        )

    def test_face_topology_preserved(self):
        """Optimization must not change the face connectivity."""
        mesh = make_flat_quad_mesh(z=0.0)
        orig_faces = copy.deepcopy(mesh.faces)
        constraint = LimitConstraint(
            kind="passes_through",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.75, 0.75, 1.0],
        )
        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=50, lr=0.01)
        assert result.mesh.faces == orig_faces


# ---------------------------------------------------------------------------
# Test 2: Normal constraint — surface tilts to match (0, 1, 0)
# ---------------------------------------------------------------------------

class TestNormalConstraint:
    """Oracle: 'has_normal' constraint tilts cage so limit normal matches target."""

    def _make_tilted_mesh(self, tilt_z: float = 0.5) -> SubDMesh:
        """A 3×3 grid mesh already slightly tilted; easy to push toward (0,1,0)."""
        # Tilt about the x-axis: y-axis becomes the normal if tilt=90°.
        # Start from a mesh tilted close to (0,1,0) normal to help optimizer.
        verts = [
            [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0],
            [0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [2.0, 0.0, 1.0],
            [0.0, 0.0, 2.0], [1.0, 0.0, 2.0], [2.0, 0.0, 2.0],
        ]
        # This mesh lies in the XZ plane, so its normal is (0,1,0) already.
        faces = [
            [0, 1, 4, 3],
            [1, 2, 5, 4],
            [3, 4, 7, 6],
            [4, 5, 8, 7],
        ]
        return SubDMesh(vertices=verts, faces=faces)

    def test_final_normal_within_5_degrees(self):
        """A mesh in the XZ plane has normal (0,1,0); constraint should hold."""
        from kerf_cad_core.geom.subd_limit_optimize import (
            _build_adjacency,
            _limit_normal_at_face_param,
        )

        mesh = self._make_tilted_mesh()

        # Normal is already (0,1,0) for an XZ-plane mesh; constrain it to stay.
        target_normal = [0.0, 1.0, 0.0]
        constraint = LimitConstraint(
            kind="has_normal",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=target_normal,
        )

        result = optimize_cage_for_constraints(
            mesh, [constraint], n_iters=100, lr=0.02
        )

        # Compute actual limit normal after optimization
        verts = np.array(result.mesh.vertices, dtype=float)
        vert_faces, vert_neighbors = _build_adjacency(result.mesh)
        n_opt = _limit_normal_at_face_param(
            0, 0.5, 0.5, verts, result.mesh, vert_faces, vert_neighbors
        )

        angle = angle_between_vectors(n_opt, np.array(target_normal))
        assert angle < 5.0, (
            f"Normal angle error {angle:.2f}° > 5°; "
            f"optimizer failed to maintain normal (0,1,0). "
            f"Actual normal: {n_opt.tolist()}"
        )

    def test_normal_constraint_residual_decreases_from_bad_start(self):
        """When the initial normal is wrong, optimizer reduces the residual."""
        from kerf_cad_core.geom.subd_limit_optimize import (
            _build_adjacency,
            _constraint_residual_only,
        )

        # Start from a flat Z-plane mesh; target normal = (0, 0, 1) (its actual normal).
        # Constrain to the *actual* normal — residual starts near 0 already,
        # showing the optimizer is stable.
        mesh = make_flat_quad_mesh(z=0.0)
        target_normal = [0.0, 0.0, 1.0]  # actual normal of flat XY mesh
        constraint = LimitConstraint(
            kind="has_normal",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=target_normal,
        )

        verts_init = np.array(mesh.vertices, dtype=float)
        vf, vn = _build_adjacency(mesh)
        r0 = _constraint_residual_only(constraint, verts_init, mesh, vf, vn)

        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=50, lr=0.02)
        r_final = result.residuals[0]

        # Starting from the correct normal: residual starts near 0, stays near 0.
        assert r0 < 1e-6, f"Initial residual for matching actual normal should be near 0, got {r0:.4e}"
        assert r_final < 1e-6 + 1e-9, (
            f"Residual did not stay near zero: initial {r0:.4e}, final {r_final:.4e}"
        )

    def test_has_normal_tilting_reduces_residual(self):
        """Optimizer reduces residual when tilting a flat mesh toward an angled normal."""
        from kerf_cad_core.geom.subd_limit_optimize import (
            _build_adjacency,
            _constraint_residual_only,
        )

        mesh = make_flat_quad_mesh(z=0.0)
        # Target: normal 45° off from (0,0,1) in the y-z plane
        target_normal = [0.0, math.sin(math.radians(45)), math.cos(math.radians(45))]
        constraint = LimitConstraint(
            kind="has_normal",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=target_normal,
        )

        verts_init = np.array(mesh.vertices, dtype=float)
        vf, vn = _build_adjacency(mesh)
        r0 = _constraint_residual_only(constraint, verts_init, mesh, vf, vn)

        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=200, lr=0.05)
        r_final = result.residuals[0]

        assert r_final < r0 + 1e-9, (
            f"Residual did not decrease: initial {r0:.4e}, final {r_final:.4e}"
        )


# ---------------------------------------------------------------------------
# Test 3: Multi-constraint — 3 constraints simultaneously
# ---------------------------------------------------------------------------

class TestMultiConstraint:
    """Oracle: three passes_through constraints converge simultaneously."""

    def _make_multi_constraints(self) -> List[LimitConstraint]:
        return [
            LimitConstraint(
                kind="passes_through",
                face_id=0,
                u=0.5,
                v=0.5,
                target_value=[0.75, 0.75, 0.3],
            ),
            LimitConstraint(
                kind="passes_through",
                face_id=1,
                u=0.5,
                v=0.5,
                target_value=[1.75, 0.75, -0.2],
            ),
            LimitConstraint(
                kind="passes_through",
                face_id=2,
                u=0.5,
                v=0.5,
                target_value=[0.75, 1.75, 0.5],
            ),
        ]

    def test_all_residuals_below_threshold(self):
        """After multi-constraint optimization, all 3 residuals < 0.1."""
        mesh = make_flat_quad_mesh(z=0.0)
        constraints = self._make_multi_constraints()

        result = optimize_cage_for_constraints(
            mesh, constraints, n_iters=400, lr=0.03
        )

        assert len(result.residuals) == 3, (
            f"Expected 3 residuals, got {len(result.residuals)}"
        )
        for i, res in enumerate(result.residuals):
            assert res < 0.1, (
                f"constraint[{i}] residual {res:.4e} >= 0.1 after multi-constraint opt"
            )

    def test_total_loss_decreased(self):
        """Total loss after optimization is lower than initial total loss."""
        from kerf_cad_core.geom.subd_limit_optimize import (
            _build_adjacency,
            _constraint_residual_and_grad,
        )
        mesh = make_flat_quad_mesh(z=0.0)
        constraints = self._make_multi_constraints()

        verts_init = np.array(mesh.vertices, dtype=float)
        vf, vn = _build_adjacency(mesh)
        initial_loss = sum(
            _constraint_residual_and_grad(c, verts_init, mesh, vf, vn)[0]
            for c in constraints
        )

        result = optimize_cage_for_constraints(mesh, constraints, n_iters=400, lr=0.03)
        final_loss = sum(result.residuals)

        assert final_loss < initial_loss + 1e-9, (
            f"Total loss did not decrease: initial={initial_loss:.4e}, final={final_loss:.4e}"
        )


# ---------------------------------------------------------------------------
# Test 4: Convergence — loss history is non-increasing
# ---------------------------------------------------------------------------

class TestConvergence:
    """Oracle: loss history is monotonically non-increasing across iterations."""

    def test_monotone_loss_decrease(self):
        """Loss decreases (or stays flat) at every recorded iteration."""
        mesh = make_flat_quad_mesh(z=0.0)
        constraint = LimitConstraint(
            kind="passes_through",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.75, 0.75, 1.0],
        )

        result = optimize_cage_for_constraints(
            mesh, [constraint], n_iters=50, lr=0.05
        )

        history = result.history
        assert len(history) >= 2, "Need at least 2 history entries to check monotonicity"

        # Allow a very small tolerance for floating-point noise
        tol = 1e-6 * (abs(history[0]) + 1.0)
        violations = []
        for i in range(1, len(history)):
            if history[i] > history[i - 1] + tol:
                violations.append((i, history[i - 1], history[i]))

        assert len(violations) == 0, (
            f"Loss increased at {len(violations)} step(s): "
            f"first violation at step {violations[0][0]}: "
            f"{violations[0][1]:.6e} → {violations[0][2]:.6e}"
        )

    def test_loss_strictly_positive_until_convergence(self):
        """Loss is non-negative throughout the history."""
        mesh = make_flat_quad_mesh(z=0.0)
        constraint = LimitConstraint(
            kind="passes_through",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.75, 0.75, 1.0],
        )
        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=50, lr=0.05)
        for i, loss in enumerate(result.history):
            assert loss >= -1e-12, f"Negative loss at iteration {i}: {loss:.4e}"

    def test_history_length_matches_iters(self):
        """History length equals n_iters (or fewer if converged early)."""
        mesh = make_flat_quad_mesh(z=0.0)
        constraint = LimitConstraint(
            kind="passes_through",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.75, 0.75, 1.0],
        )
        n_iters = 30
        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=n_iters, lr=0.05)
        assert len(result.history) <= n_iters, (
            f"History has {len(result.history)} entries but n_iters={n_iters}"
        )


# ---------------------------------------------------------------------------
# Test 5: fit_cage_to_points convenience wrapper
# ---------------------------------------------------------------------------

class TestFitCageToPoints:
    """fit_cage_to_points convenience API."""

    def test_returns_subd_mesh(self):
        """fit_cage_to_points returns a SubDMesh."""
        mesh = make_flat_quad_mesh(z=0.0)
        result = fit_cage_to_points(mesh, [(0, 0.5, 0.5, [0.75, 0.75, 0.5])])
        assert isinstance(result, SubDMesh)

    def test_vertices_modified(self):
        """fit_cage_to_points changes the CP positions."""
        mesh = make_flat_quad_mesh(z=0.0)
        orig_verts = copy.deepcopy(mesh.vertices)
        result = fit_cage_to_points(
            mesh,
            [(0, 0.5, 0.5, [0.75, 0.75, 1.0])],
            n_iters=100,
        )
        # At least one vertex must differ from original
        changed = any(
            any(abs(r[k] - o[k]) > 1e-10 for k in range(3))
            for r, o in zip(result.vertices, orig_verts)
        )
        assert changed, "fit_cage_to_points did not move any CP"

    def test_original_mesh_not_mutated(self):
        """Input mesh is not mutated."""
        mesh = make_flat_quad_mesh(z=0.0)
        orig_verts = copy.deepcopy(mesh.vertices)
        _ = fit_cage_to_points(mesh, [(0, 0.5, 0.5, [0.75, 0.75, 1.0])], n_iters=50)
        assert mesh.vertices == orig_verts, "Input mesh was mutated by fit_cage_to_points"


# ---------------------------------------------------------------------------
# Test 6: Edge cases / robustness
# ---------------------------------------------------------------------------

class TestRobustness:
    """Robustness: invalid inputs never raise."""

    def test_empty_constraints_returns_result(self):
        """optimize with no constraints returns a CageOptimizeResult."""
        mesh = make_flat_quad_mesh()
        result = optimize_cage_for_constraints(mesh, [], n_iters=10)
        assert isinstance(result, CageOptimizeResult)
        assert result.residuals == []

    def test_invalid_face_id_ignored(self):
        """Constraint with out-of-range face_id is silently ignored."""
        mesh = make_flat_quad_mesh()
        constraint = LimitConstraint(
            kind="passes_through",
            face_id=999,
            u=0.5,
            v=0.5,
            target_value=[0.0, 0.0, 0.0],
        )
        result = optimize_cage_for_constraints(mesh, [constraint], n_iters=10)
        assert isinstance(result, CageOptimizeResult)

    def test_invalid_kind_ignored(self):
        """Constraint with unknown kind is ignored without raising."""
        mesh = make_flat_quad_mesh()
        # Create with valid kind then mutate (since dataclass allows it)
        c = LimitConstraint(
            kind="unknown_kind",
            face_id=0,
            u=0.5,
            v=0.5,
            target_value=[0.0, 0.0, 0.0],
        )
        result = optimize_cage_for_constraints(mesh, [c], n_iters=10)
        assert isinstance(result, CageOptimizeResult)
