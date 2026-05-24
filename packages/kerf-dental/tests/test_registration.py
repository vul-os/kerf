"""
Tests for kerf_dental.registration — ICP multi-scan registration + deviation map.

Validation strategy (Besl & McKay §V; Rusinkiewicz & Levoy §5):
  1. Synthetic ground-truth test: register a point cloud against a rigidly
     transformed copy; recovered transform must match GT within tolerance.
  2. Deviation map zero-case: deviation_map of identical meshes ≈ 0.
  3. API contract: result types and shape invariants.
  4. Convergence / iteration counts on well-conditioned problems.
  5. Degenerate inputs: < 3 points raises ValueError.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.registration import (
    RegistrationResult,
    DeviationResult,
    register_scans,
    deviation_map,
    compose_transforms,
    invert_transform,
    apply_transform,
    _outlier_mask,
    _compute_vertex_normals,
    _umeyama_rotation,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _unit_sphere_pts(n: int = 500, seed: int = 0) -> np.ndarray:
    """Uniformly distributed points on the unit sphere (mm-scale radius 5)."""
    rng = np.random.default_rng(seed)
    pts = rng.standard_normal((n, 3))
    pts /= np.linalg.norm(pts, axis=1, keepdims=True)
    return pts * 5.0  # radius 5 mm


def _dental_arch_pts(n: int = 400, seed: int = 1) -> np.ndarray:
    """Synthetic dental arch: parabolic curve + noise (approximates IOS scan cloud)."""
    rng = np.random.default_rng(seed)
    t = np.linspace(-math.pi / 2, math.pi / 2, n)
    x = 15.0 * np.cos(t)
    y = 10.0 * np.sin(t)
    z = rng.uniform(-1.0, 1.0, n)
    pts = np.column_stack([x, y, z])
    pts += rng.standard_normal((n, 3)) * 0.05  # 50 µm scanner noise
    return pts


def _rot_from_euler(rx: float, ry: float, rz: float) -> np.ndarray:
    """Rotation matrix from Euler angles (radians, intrinsic ZYX)."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def _make_gt_transform(
    rx: float = 0.05, ry: float = 0.03, rz: float = 0.04,
    tx: float = 1.0, ty: float = -0.5, tz: float = 0.3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (T_4x4, R_3x3, t_3) for a known rigid body transform."""
    R = _rot_from_euler(rx, ry, rz)
    t = np.array([tx, ty, tz])
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    return T, R, t


def _apply_gt(pts: np.ndarray, R: np.ndarray, t: np.ndarray) -> np.ndarray:
    return (R @ pts.T).T + t


def _rot_error_deg(R_est: np.ndarray, R_gt: np.ndarray) -> float:
    """Angular error between two rotation matrices (degrees)."""
    # ||R_est R_gt^T - I|| → angle via trace
    dR = R_est @ R_gt.T
    trace = np.clip((np.trace(dR) - 1.0) / 2.0, -1.0, 1.0)
    return math.degrees(math.acos(trace))


# ===========================================================================
# 1. Ground-truth registration test (core validation oracle)
# ===========================================================================

class TestGroundTruthRegistration:
    """Register a cloud against a rigidly-transformed copy → recover GT transform."""

    def _run_oracle(
        self,
        cloud: np.ndarray,
        R_gt: np.ndarray,
        t_gt: np.ndarray,
        method: str,
        rot_tol_deg: float = 0.5,
        trans_tol_mm: float = 0.5,
    ):
        source = cloud
        target = _apply_gt(cloud, R_gt, t_gt)  # shifted cloud = target

        result = register_scans(source, target, method=method,
                                max_iterations=100, convergence_tol=1e-7)
        assert isinstance(result, RegistrationResult)

        rot_err = _rot_error_deg(result.rotation, R_gt)
        trans_err = float(np.linalg.norm(result.translation - t_gt))

        assert rot_err < rot_tol_deg, (
            f"[{method}] Rotation error {rot_err:.4f}° > {rot_tol_deg}°"
        )
        assert trans_err < trans_tol_mm, (
            f"[{method}] Translation error {trans_err:.4f} mm > {trans_tol_mm} mm"
        )
        return result

    # --- Sphere cloud --- point-to-point -----------------------------------

    def test_sphere_point_to_point_small_rotation(self):
        """Sphere cloud, small rotation (~5°), point-to-point ICP recovers GT."""
        cloud = _unit_sphere_pts(500)
        _, R_gt, t_gt = _make_gt_transform(rx=0.05, ry=0.03, rz=0.04,
                                           tx=0.5, ty=-0.3, tz=0.2)
        self._run_oracle(cloud, R_gt, t_gt, "point_to_point",
                         rot_tol_deg=0.5, trans_tol_mm=0.5)

    def test_sphere_point_to_plane_small_rotation(self):
        """Sphere cloud, small rotation (~5°), point-to-plane ICP recovers GT."""
        cloud = _unit_sphere_pts(500)
        _, R_gt, t_gt = _make_gt_transform(rx=0.05, ry=0.03, rz=0.04,
                                           tx=0.5, ty=-0.3, tz=0.2)
        self._run_oracle(cloud, R_gt, t_gt, "point_to_plane",
                         rot_tol_deg=0.5, trans_tol_mm=0.5)

    # --- Dental arch cloud -------------------------------------------------

    def test_dental_arch_point_to_point(self):
        """Dental arch parabola, small perturbation, point-to-point."""
        cloud = _dental_arch_pts(400)
        _, R_gt, t_gt = _make_gt_transform(rx=0.02, ry=0.01, rz=0.03,
                                           tx=0.4, ty=0.2, tz=-0.1)
        self._run_oracle(cloud, R_gt, t_gt, "point_to_point",
                         rot_tol_deg=0.5, trans_tol_mm=0.5)

    def test_dental_arch_point_to_plane(self):
        """Dental arch parabola, small perturbation, point-to-plane."""
        cloud = _dental_arch_pts(400)
        _, R_gt, t_gt = _make_gt_transform(rx=0.02, ry=0.01, rz=0.03,
                                           tx=0.4, ty=0.2, tz=-0.1)
        self._run_oracle(cloud, R_gt, t_gt, "point_to_plane",
                         rot_tol_deg=0.5, trans_tol_mm=0.5)

    # --- Pure translation --------------------------------------------------

    def test_pure_translation_recovers_t(self):
        """Translation-only perturbation (R=I, t=[2,1,-0.5])."""
        cloud = _unit_sphere_pts(300)
        R_gt = np.eye(3)
        t_gt = np.array([2.0, 1.0, -0.5])
        self._run_oracle(cloud, R_gt, t_gt, "point_to_point",
                         rot_tol_deg=0.1, trans_tol_mm=0.05)

    # --- Pure rotation -----------------------------------------------------

    def test_pure_rotation_recovers_R(self):
        """Pure rotation (t=0) — small angle (~3°)."""
        cloud = _dental_arch_pts(400, seed=7)
        R_gt = _rot_from_euler(0.03, 0.02, 0.01)
        t_gt = np.zeros(3)
        self._run_oracle(cloud, R_gt, t_gt, "point_to_point",
                         rot_tol_deg=0.5, trans_tol_mm=0.1)

    # --- Residual RMS near 0 on aligned clouds ----------------------------

    def test_rms_near_zero_after_registration(self):
        """After registration of identical-layout clouds, RMS < 0.1 mm."""
        cloud = _dental_arch_pts(400)
        result = register_scans(cloud, cloud, method="point_to_point",
                                max_iterations=30)
        assert result.rms_mm < 0.1, f"RMS {result.rms_mm:.6f} mm on identical clouds"

    def test_rms_near_zero_after_registration_plane(self):
        """Point-to-plane on identical clouds — RMS < 0.1 mm."""
        cloud = _dental_arch_pts(400)
        result = register_scans(cloud, cloud, method="point_to_plane",
                                max_iterations=30)
        assert result.rms_mm < 0.1


# ===========================================================================
# 2. Deviation map — zero-case oracle
# ===========================================================================

class TestDeviationMap:
    """Deviation map of identical meshes ≈ 0."""

    def test_identical_point_clouds_deviation_zero(self):
        """deviation_map of cloud against itself: RMS < 1e-9 mm."""
        cloud = _unit_sphere_pts(300)
        result = deviation_map(cloud, cloud)
        assert isinstance(result, DeviationResult)
        assert result.rms_mm < 1e-9, f"RMS {result.rms_mm} on identical clouds"

    def test_identical_point_clouds_unsigned_all_zero(self):
        """All unsigned distances must be ~0 for identical clouds."""
        cloud = _dental_arch_pts(300)
        result = deviation_map(cloud, cloud)
        assert np.all(result.unsigned_distances < 1e-9)

    def test_identical_point_clouds_p95_zero(self):
        """P95 deviation on identical clouds < 1e-9 mm."""
        cloud = _unit_sphere_pts(300)
        result = deviation_map(cloud, cloud)
        assert result.p95_mm < 1e-9

    def test_identical_point_clouds_mean_signed_near_zero(self):
        """Mean signed deviation on identical clouds ~ 0."""
        cloud = _dental_arch_pts(300)
        result = deviation_map(cloud, cloud)
        assert abs(result.mean_signed_mm) < 1e-9

    def test_translated_single_point_unsigned_equals_translation(self):
        """Single point shifted by known distance: unsigned distance = shift."""
        # Use a single isolated point and its shifted copy as target
        # Target: origin; source: shifted by 3 mm along X
        target = np.array([[0.0, 0.0, 0.0]])
        source = np.array([[3.0, 0.0, 0.0]])
        result = deviation_map(source, target)
        assert abs(result.rms_mm - 3.0) < 1e-9, f"RMS {result.rms_mm} != 3.0"
        assert abs(result.unsigned_distances[0] - 3.0) < 1e-9

    def test_deviation_map_with_faces(self):
        """Signed deviation with face normals: identical mesh → 0."""
        # Simple triangle mesh: equilateral triangle fan
        n = 8
        angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
        verts = np.column_stack([
            5.0 * np.cos(angles),
            5.0 * np.sin(angles),
            np.zeros(n),
        ])
        # Fan triangles from centroid (index n)
        verts = np.vstack([verts, [0.0, 0.0, 0.0]])
        faces = np.array([[i, (i + 1) % n, n] for i in range(n)])

        result = deviation_map(verts, verts, target_faces=faces)
        assert result.rms_mm < 1e-9

    def test_deviation_result_shapes(self):
        """DeviationResult arrays have consistent shapes."""
        cloud = _unit_sphere_pts(200)
        result = deviation_map(cloud, cloud)
        assert result.source_vertices.shape == (200, 3)
        assert result.signed_distances.shape == (200,)
        assert result.unsigned_distances.shape == (200,)

    def test_deviation_after_registration(self):
        """deviation_map after register_scans of known transform ≈ 0."""
        cloud = _dental_arch_pts(300)
        _, R_gt, t_gt = _make_gt_transform(rx=0.03, ry=0.02, rz=0.01,
                                           tx=0.5, ty=-0.2, tz=0.1)
        target = _apply_gt(cloud, R_gt, t_gt)
        result_reg = register_scans(cloud, target, method="point_to_point")
        result_dev = deviation_map(result_reg.aligned_source, target)
        # After good registration, deviation should be small (< 0.5 mm)
        assert result_dev.rms_mm < 0.5, (
            f"Post-registration deviation RMS {result_dev.rms_mm:.4f} mm too large"
        )


# ===========================================================================
# 3. API contract / shape invariants
# ===========================================================================

class TestAPIContract:
    """RegistrationResult and DeviationResult type/shape checks."""

    def test_registration_result_is_dataclass(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert isinstance(result, RegistrationResult)

    def test_transform_is_4x4(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert result.transform.shape == (4, 4)

    def test_rotation_is_3x3(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert result.rotation.shape == (3, 3)

    def test_translation_is_3(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert result.translation.shape == (3,)

    def test_rotation_is_orthonormal(self):
        """R^T R ≈ I and det(R) ≈ 1."""
        cloud = _dental_arch_pts(200)
        _, R_gt, t_gt = _make_gt_transform(rx=0.04, ry=0.02, rz=0.03,
                                           tx=0.3, ty=-0.2, tz=0.1)
        target = _apply_gt(cloud, R_gt, t_gt)
        result = register_scans(cloud, target)
        R = result.rotation
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-10), "R not orthonormal"
        assert abs(np.linalg.det(R) - 1.0) < 1e-10, "det(R) != 1"

    def test_transform_top_row_homogeneous(self):
        """Bottom row of T must be [0, 0, 0, 1]."""
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert np.allclose(result.transform[3, :], [0, 0, 0, 1], atol=1e-12)

    def test_transform_r_t_consistent(self):
        """T[:3,:3] == rotation and T[:3,3] == translation."""
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert np.allclose(result.transform[:3, :3], result.rotation)
        assert np.allclose(result.transform[:3, 3], result.translation)

    def test_aligned_source_same_shape(self):
        cloud = _unit_sphere_pts(300)
        result = register_scans(cloud, cloud)
        assert result.aligned_source.shape == cloud.shape

    def test_rms_mm_is_non_negative(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert result.rms_mm >= 0.0

    def test_iterations_positive(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert result.iterations >= 1

    def test_inlier_fraction_in_01(self):
        cloud = _unit_sphere_pts(200)
        result = register_scans(cloud, cloud)
        assert 0.0 <= result.inlier_fraction <= 1.0

    def test_converged_flag_is_bool(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud)
        assert isinstance(result.converged, bool)

    def test_point_to_point_method(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud, method="point_to_point")
        assert isinstance(result, RegistrationResult)

    def test_point_to_plane_method(self):
        cloud = _unit_sphere_pts(100)
        result = register_scans(cloud, cloud, method="point_to_plane")
        assert isinstance(result, RegistrationResult)

    def test_subsample_param(self):
        """subsample param runs without error; aligned_source still full size."""
        cloud = _dental_arch_pts(500)
        result = register_scans(cloud, cloud, subsample=100)
        assert result.aligned_source.shape == (500, 3)


# ===========================================================================
# 4. Convergence behaviour
# ===========================================================================

class TestConvergence:

    def test_converges_in_few_iterations_identical(self):
        """On identical clouds, ICP should converge immediately (≤ 5 iter)."""
        cloud = _unit_sphere_pts(300)
        result = register_scans(cloud, cloud, max_iterations=50,
                                convergence_tol=1e-6)
        assert result.converged or result.iterations <= 5

    def test_max_iterations_respected(self):
        """iterations ≤ max_iterations always."""
        cloud = _dental_arch_pts(200)
        for max_it in [1, 5, 20]:
            result = register_scans(cloud, cloud, max_iterations=max_it)
            assert result.iterations <= max_it

    def test_more_iterations_not_worse(self):
        """RMS(100 iter) ≤ RMS(5 iter) for a non-trivial problem."""
        cloud = _dental_arch_pts(300)
        _, R_gt, t_gt = _make_gt_transform(rx=0.05, ry=0.03, rz=0.04,
                                           tx=1.0, ty=-0.5, tz=0.3)
        target = _apply_gt(cloud, R_gt, t_gt)
        r5 = register_scans(cloud, target, max_iterations=5)
        r100 = register_scans(cloud, target, max_iterations=100)
        # 100 iterations should be at least as good as 5
        assert r100.rms_mm <= r5.rms_mm + 1e-3


# ===========================================================================
# 5. Input validation
# ===========================================================================

class TestInputValidation:

    def test_too_few_source_points_raises(self):
        with pytest.raises(ValueError, match="source"):
            register_scans([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
                           _unit_sphere_pts(10))

    def test_too_few_target_points_raises(self):
        with pytest.raises(ValueError, match="target"):
            register_scans(_unit_sphere_pts(10),
                           [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])

    def test_wrong_shape_raises(self):
        with pytest.raises(ValueError):
            register_scans(np.zeros((10, 2)), np.zeros((10, 3)))

    def test_list_input_accepted(self):
        """Python list input (not ndarray) is accepted."""
        src = [[float(i), 0.0, 0.0] for i in range(50)]
        tgt = [[float(i), 0.0, 0.0] for i in range(50)]
        result = register_scans(src, tgt)
        assert isinstance(result, RegistrationResult)

    def test_deviation_map_list_input(self):
        cloud = [[float(i), 0.0, 0.0] for i in range(50)]
        result = deviation_map(cloud, cloud)
        assert result.rms_mm < 1e-9


# ===========================================================================
# 6. Utility functions
# ===========================================================================

class TestUtils:

    def test_compose_transforms_identity(self):
        """Composing two identities → identity."""
        T = compose_transforms(np.eye(4), np.eye(4))
        assert np.allclose(T, np.eye(4))

    def test_invert_transform_identity(self):
        T_inv = invert_transform(np.eye(4))
        assert np.allclose(T_inv, np.eye(4))

    def test_invert_then_apply_is_identity(self):
        """T · T^{-1} = I."""
        R = _rot_from_euler(0.1, 0.2, 0.3)
        t = np.array([1.0, -2.0, 0.5])
        T = np.eye(4)
        T[:3, :3] = R
        T[:3, 3] = t
        T_inv = invert_transform(T)
        assert np.allclose(T @ T_inv, np.eye(4), atol=1e-12)

    def test_apply_transform_shape(self):
        T = np.eye(4)
        pts = _unit_sphere_pts(50)
        out = apply_transform(T, pts)
        assert out.shape == pts.shape

    def test_apply_identity_unchanged(self):
        pts = _dental_arch_pts(100)
        out = apply_transform(np.eye(4), pts)
        assert np.allclose(out, pts)

    def test_outlier_mask_removes_outliers(self):
        """Large outlier distance should be flagged as outlier."""
        d = np.array([0.1, 0.12, 0.11, 0.09, 0.1, 100.0])  # last is outlier
        mask = _outlier_mask(d, k=3.0)
        assert not mask[-1], "Large outlier should be rejected"
        assert mask[:5].all(), "Inliers should be kept"

    def test_outlier_mask_empty(self):
        mask = _outlier_mask(np.array([]))
        assert len(mask) == 0

    def test_vertex_normals_flat_quad(self):
        """Four vertices on the XY plane: normals should all be ±Z."""
        verts = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
        ])
        faces = np.array([[0, 1, 2], [0, 2, 3]])
        normals = _compute_vertex_normals(verts, faces)
        for n in normals:
            if np.linalg.norm(n) > 1e-6:
                assert abs(abs(n[2]) - 1.0) < 0.01, f"Normal not Z-aligned: {n}"

    def test_umeyama_rotation_identity(self):
        """Optimal rotation of identical sets = I."""
        pts = _unit_sphere_pts(100)
        R = _umeyama_rotation(pts, pts)
        assert np.allclose(R, np.eye(3), atol=1e-10)

    def test_umeyama_rotation_known_90deg(self):
        """90° rotation around Z recovered exactly."""
        rng = np.random.default_rng(42)
        pts = rng.standard_normal((50, 3))
        R_gt = _rot_from_euler(0.0, 0.0, math.pi / 2)
        pts_rot = (R_gt @ pts.T).T
        R_est = _umeyama_rotation(pts, pts_rot)
        assert np.allclose(R_est, R_gt, atol=1e-10)


# ===========================================================================
# 7. Module import smoke test
# ===========================================================================

class TestModuleImport:
    def test_import_registration(self):
        import kerf_dental.registration  # noqa: F401

    def test_public_api_accessible(self):
        from kerf_dental.registration import (
            register_scans,
            deviation_map,
            RegistrationResult,
            DeviationResult,
            compose_transforms,
            invert_transform,
            apply_transform,
        )
        assert callable(register_scans)
        assert callable(deviation_map)
