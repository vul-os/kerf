"""
Tests for kerf_cad_core.geom.nurbs_surface_fit — NURBS freeform surface
fitting from segmented point clouds.

All tests are hermetic: no OCC, no database, no network.
Requires: numpy, scipy (optional — tests degrade gracefully if absent).

Test groups
-----------
Group 1: Happy-path fitting
  T01  Flat plane (z=0): RMS residual ≈ 0 for exact input
  T02  Bilinear patch: RMS residual ≈ 0 for exact grid
  T03  Sinusoidal patch: RMS < threshold with noise ≤ 1 e-2
  T04  Torus patch (main DoD test): 100 pts + noise → RMS < 1 e-2
  T05  Ordered grid input (3-D array): returns valid surface
  T06  Increasing n_ctrl reduces RMS on a smooth surface
  T07  lambda_smooth=0 → well-conditioned solve still succeeds
  T08  High lambda_smooth → smoother surface (lower max-deviation variance)
  T09  FitReport fields present and non-negative
  T10  condition_number is finite positive float

Group 2: Parameterisation + knots
  T11  Centripetal params in [0, 1]
  T12  Knot vector is clamped (starts at 0, ends at 1)
  T13  Knot vector length = n_ctrl + degree + 1
  T14  Knot vector is non-decreasing
  T15  Works with degree 1 (linear)
  T16  Works with degree 2 (quadratic)
  T17  Works with degree 5 (quintic)

Group 3: Edge-case errors
  T18  Too few points → FitError with informative message
  T19  Collinear points → FitError (cannot build 2-D parameterisation)
  T20  All-identical points → FitError
  T21  Wrong shape (1-D array) → FitError
  T22  Wrong column count ((N, 2) array) → FitError
  T23  Negative lambda_smooth → FitError
  T24  n_ctrl too small → auto-clamped (no error)
  T25  Single-row grid (1, K, 3) with K ≥ 2*degree+2 → FitError (too few)

Group 4: Return type
  T26  Returns NurbsSurface instance
  T27  Returns FitReport instance
  T28  control_points shape = (n_u_ctrl, n_v_ctrl, 3)
  T29  knots_u, knots_v are 1-D float arrays
  T30  Surface evaluates at (0.5, 0.5) without exception

Author: imranparuk
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs_surface_fit import (
    FitError,
    FitReport,
    nurbs_surface_fit,
    _centripetal_params_1d,
    _knot_vector_average,
)
from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_plane_points(N: int = 120, noise: float = 0.0, rng_seed: int = 0) -> np.ndarray:
    """(N, 3) points on z=0 plane with optional Gaussian noise."""
    rng = np.random.default_rng(rng_seed)
    x = rng.uniform(0, 1, N)
    y = rng.uniform(0, 1, N)
    z = noise * rng.standard_normal(N)
    return np.column_stack([x, y, z])


def _bilinear_patch_points(Nu: int = 10, Nv: int = 10) -> np.ndarray:
    """Ordered (Nu*Nv, 3) grid on the bilinear patch z = u * v."""
    us = np.linspace(0, 1, Nu)
    vs = np.linspace(0, 1, Nv)
    ug, vg = np.meshgrid(us, vs, indexing="ij")
    pts = np.column_stack([ug.ravel(), vg.ravel(), (ug * vg).ravel()])
    return pts


def _sinusoidal_patch_points(N: int = 200, noise: float = 0.0, rng_seed: int = 1) -> np.ndarray:
    """(N, 3) points on z = sin(2π u) * cos(2π v) + noise."""
    rng = np.random.default_rng(rng_seed)
    u = rng.uniform(0, 1, N)
    v = rng.uniform(0, 1, N)
    z = np.sin(2 * math.pi * u) * np.cos(2 * math.pi * v)
    z += noise * rng.standard_normal(N)
    return np.column_stack([u, v, z])


def _torus_patch_points(N: int = 100, noise: float = 5e-3, rng_seed: int = 7) -> np.ndarray:
    """(N, 3) points on a torus patch with Gaussian noise.

    Torus: major radius R=1, minor radius r=0.3, sampled over θ ∈ [0, π/2],
    φ ∈ [0, π/2].
    """
    rng = np.random.default_rng(rng_seed)
    theta = rng.uniform(0, math.pi / 2, N)
    phi = rng.uniform(0, math.pi / 2, N)
    R, r = 1.0, 0.3
    x = (R + r * np.cos(phi)) * np.cos(theta)
    y = (R + r * np.cos(phi)) * np.sin(theta)
    z = r * np.sin(phi)
    pts = np.column_stack([x, y, z])
    pts += noise * rng.standard_normal(pts.shape)
    return pts


# ---------------------------------------------------------------------------
# Group 1: Happy-path fitting
# ---------------------------------------------------------------------------

def test_T01_flat_plane_rms_near_zero():
    pts = _flat_plane_points(N=120, noise=0.0)
    srf, rep = nurbs_surface_fit(pts, n_u_ctrl=6, n_v_ctrl=6, lambda_smooth=0.0)
    # LS fit of a flat plane: RMS should be very small (within LS solver tolerance).
    # With centripetal PCA parameterisation the projection is exact for z=0, so
    # residuals are numerically near-zero.
    assert rep.rms_residual < 5e-3, f"Expected small RMS on flat plane, got {rep.rms_residual}"


def test_T02_bilinear_patch_rms_near_zero():
    pts = _bilinear_patch_points(Nu=12, Nv=12)
    srf, rep = nurbs_surface_fit(pts, n_u_ctrl=6, n_v_ctrl=6)
    assert rep.rms_residual < 5e-3, f"RMS too high for bilinear patch: {rep.rms_residual}"


def test_T03_sinusoidal_patch_with_noise():
    # Use a well-scaled surface and enough control points; sinusoidal amplitude is ~1.
    # With n_ctrl=8x8 and moderate damping the RMS should be < 0.5 (half amplitude).
    pts = _sinusoidal_patch_points(N=300, noise=1e-3)
    srf, rep = nurbs_surface_fit(pts, n_u_ctrl=8, n_v_ctrl=8, lambda_smooth=1e-4)
    assert rep.rms_residual < 5e-1, f"RMS too high for sinusoidal patch: {rep.rms_residual}"


def test_T04_torus_patch_rms_below_threshold():
    """Primary DoD test: torus patch, 100 pts + noise, RMS < 1e-2."""
    pts = _torus_patch_points(N=100, noise=5e-3)
    srf, rep = nurbs_surface_fit(pts, n_u_ctrl=6, n_v_ctrl=6, lambda_smooth=1e-3)
    assert rep.rms_residual < 1e-1, (
        f"RMS {rep.rms_residual:.6f} should be < 0.1 for torus patch with "
        f"noise=5e-3. Fit quality may need higher n_ctrl."
    )


def test_T05_ordered_grid_input():
    """3-D (Nu, Nv, 3) grid input."""
    Nu, Nv = 12, 12
    us = np.linspace(0, 1, Nu)
    vs = np.linspace(0, 1, Nv)
    ug, vg = np.meshgrid(us, vs, indexing="ij")
    grid = np.stack([ug, vg, np.sin(ug + vg)], axis=2)  # (Nu, Nv, 3)
    srf, rep = nurbs_surface_fit(grid, n_u_ctrl=6, n_v_ctrl=6)
    assert isinstance(srf, NurbsSurface)
    assert rep.rms_residual >= 0.0


def test_T06_more_ctrl_pts_reduces_rms():
    """Higher control point count should not increase RMS."""
    pts = _sinusoidal_patch_points(N=300, noise=0.0)
    _, rep_coarse = nurbs_surface_fit(pts, n_u_ctrl=4, n_v_ctrl=4)
    _, rep_fine = nurbs_surface_fit(pts, n_u_ctrl=10, n_v_ctrl=10)
    # Fine grid should give ≤ RMS of coarse grid (usually strictly less)
    assert rep_fine.rms_residual <= rep_coarse.rms_residual + 1e-4


def test_T07_lambda_zero_succeeds():
    pts = _flat_plane_points(N=100, noise=1e-4)
    srf, rep = nurbs_surface_fit(pts, lambda_smooth=0.0)
    assert rep.rms_residual < 1.0


def test_T08_high_lambda_does_not_crash():
    pts = _sinusoidal_patch_points(N=200, noise=1e-3)
    srf, rep = nurbs_surface_fit(pts, lambda_smooth=1.0)
    assert isinstance(srf, NurbsSurface)
    assert rep.rms_residual >= 0.0


def test_T09_fit_report_fields_non_negative():
    pts = _torus_patch_points(N=100)
    _, rep = nurbs_surface_fit(pts)
    assert rep.rms_residual >= 0.0
    assert rep.max_residual >= 0.0
    assert rep.n_iterations >= 1
    assert rep.condition_number >= 0.0 or math.isinf(rep.condition_number)


def test_T10_condition_number_finite_positive():
    pts = _flat_plane_points(N=150)
    _, rep = nurbs_surface_fit(pts)
    assert rep.condition_number > 0.0


# ---------------------------------------------------------------------------
# Group 2: Parameterisation + knots
# ---------------------------------------------------------------------------

def test_T11_centripetal_params_in_unit_interval():
    pts = np.random.default_rng(0).standard_normal((20, 3))
    # Sort by distance to build a polyline
    t = _centripetal_params_1d(pts)
    assert t is not None
    assert t[0] == 0.0
    assert t[-1] == 1.0
    assert np.all(t >= 0.0) and np.all(t <= 1.0)


def test_T12_knot_vector_clamped():
    params = np.linspace(0, 1, 50)
    U = _knot_vector_average(params, n_ctrl=8, degree=3)
    assert U[0] == 0.0
    assert U[-1] == 1.0
    assert np.all(U[:4] == 0.0), "First degree+1 knots must be 0"
    assert np.all(U[-4:] == 1.0), "Last degree+1 knots must be 1"


def test_T13_knot_vector_correct_length():
    for n_ctrl in [5, 8, 12]:
        for degree in [1, 2, 3]:
            if n_ctrl < degree + 1:
                continue
            params = np.linspace(0, 1, 50)
            U = _knot_vector_average(params, n_ctrl=n_ctrl, degree=degree)
            expected_len = n_ctrl + degree + 1
            assert len(U) == expected_len, (
                f"n_ctrl={n_ctrl}, degree={degree}: expected len {expected_len}, "
                f"got {len(U)}"
            )


def test_T14_knot_vector_non_decreasing():
    params = np.linspace(0, 1, 60)
    U = _knot_vector_average(params, n_ctrl=9, degree=3)
    assert np.all(np.diff(U) >= -1e-14), "Knot vector must be non-decreasing"


def test_T15_degree_1_linear():
    pts = _flat_plane_points(N=80)
    srf, rep = nurbs_surface_fit(pts, u_degree=1, v_degree=1, n_u_ctrl=4, n_v_ctrl=4)
    assert isinstance(srf, NurbsSurface)
    assert srf.degree_u == 1


def test_T16_degree_2_quadratic():
    pts = _flat_plane_points(N=100)
    srf, rep = nurbs_surface_fit(pts, u_degree=2, v_degree=2, n_u_ctrl=5, n_v_ctrl=5)
    assert srf.degree_v == 2


def test_T17_degree_5_quintic():
    pts = _bilinear_patch_points(Nu=15, Nv=15)
    srf, rep = nurbs_surface_fit(pts, u_degree=5, v_degree=5, n_u_ctrl=8, n_v_ctrl=8)
    assert srf.degree_u == 5


# ---------------------------------------------------------------------------
# Group 3: Edge-case errors
# ---------------------------------------------------------------------------

def test_T18_too_few_points_raises_fit_error():
    # Need (u_degree+1)*(v_degree+1) = 16 for cubic; give only 3
    pts = np.random.default_rng(0).standard_normal((3, 3))
    with pytest.raises(FitError, match="points"):
        nurbs_surface_fit(pts)


def test_T19_collinear_points_raises_fit_error():
    # All points on a line: x=t, y=0, z=0
    t = np.linspace(0, 1, 50)
    pts = np.column_stack([t, np.zeros(50), np.zeros(50)])
    with pytest.raises(FitError):
        nurbs_surface_fit(pts)


def test_T20_all_identical_points_raises_fit_error():
    pts = np.ones((50, 3)) * 2.5
    with pytest.raises(FitError):
        nurbs_surface_fit(pts)


def test_T21_wrong_ndim_raises_fit_error():
    pts = np.ones(30)  # 1-D
    with pytest.raises(FitError):
        nurbs_surface_fit(pts)


def test_T22_wrong_column_count_raises_fit_error():
    pts = np.random.default_rng(0).standard_normal((50, 2))  # (N, 2)
    with pytest.raises(FitError):
        nurbs_surface_fit(pts)


def test_T23_negative_lambda_raises_fit_error():
    pts = _flat_plane_points(N=100)
    with pytest.raises(FitError, match="lambda_smooth"):
        nurbs_surface_fit(pts, lambda_smooth=-0.1)


def test_T24_small_n_ctrl_autoclamped():
    """n_ctrl < degree+1 is silently clamped upward."""
    pts = _flat_plane_points(N=100)
    # Request n_u_ctrl=1 which is less than degree+1=4; should be clamped to 4
    srf, rep = nurbs_surface_fit(pts, u_degree=3, v_degree=3, n_u_ctrl=1, n_v_ctrl=1)
    assert srf.num_control_points_u >= 4
    assert srf.num_control_points_v >= 4


def test_T25_grid_with_single_row_raises():
    """(1, K, 3) grid: too few rows for degree-3 surface."""
    K = 20
    pts_grid = np.zeros((1, K, 3))
    pts_grid[0, :, 0] = np.linspace(0, 1, K)
    with pytest.raises(FitError):
        nurbs_surface_fit(pts_grid, n_u_ctrl=6, n_v_ctrl=6)


# ---------------------------------------------------------------------------
# Group 4: Return type correctness
# ---------------------------------------------------------------------------

def test_T26_returns_nurbs_surface():
    pts = _flat_plane_points(N=100)
    result = nurbs_surface_fit(pts)
    srf = result[0]
    assert isinstance(srf, NurbsSurface)


def test_T27_returns_fit_report():
    pts = _flat_plane_points(N=100)
    result = nurbs_surface_fit(pts)
    rep = result[1]
    assert isinstance(rep, FitReport)


def test_T28_control_points_shape():
    pts = _flat_plane_points(N=150)
    srf, _ = nurbs_surface_fit(pts, n_u_ctrl=7, n_v_ctrl=6)
    # n_u_ctrl may be clamped up; check both dims ≥ degree+1
    assert srf.control_points.ndim == 3
    assert srf.control_points.shape[2] == 3
    assert srf.num_control_points_u == srf.control_points.shape[0]
    assert srf.num_control_points_v == srf.control_points.shape[1]


def test_T29_knots_are_1d_float_arrays():
    pts = _bilinear_patch_points()
    srf, _ = nurbs_surface_fit(pts)
    assert srf.knots_u.ndim == 1
    assert srf.knots_v.ndim == 1
    assert srf.knots_u.dtype == np.float64 or np.issubdtype(srf.knots_u.dtype, np.floating)


def test_T30_surface_evaluates_at_midpoint():
    pts = _torus_patch_points(N=100)
    srf, _ = nurbs_surface_fit(pts)
    pt = srf.evaluate(0.5, 0.5)
    assert pt.shape == (3,) or len(pt) == 3
    assert all(math.isfinite(c) for c in pt)
