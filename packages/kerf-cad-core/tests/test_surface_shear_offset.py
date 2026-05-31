"""
Tests for kerf_cad_core.geom.surface_shear_offset
==================================================
NURBS-SURFACE-SHEAR-OFFSET: apply_shear_offset, ShearMatrix, SurfaceShearOffsetResult

References
----------
* Piegl & Tiller, "The NURBS Book" §6.1 (affine maps on NURBS).
* Mortenson, "Geometric Modeling" §4.8 (shear as off-diagonal linear map).
"""

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_shear_offset import (
    ShearMatrix,
    SurfaceShearOffsetResult,
    apply_shear_offset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_simple_surface(nu: int = 3, nv: int = 4) -> NurbsSurface:
    """Degree-(1,1) non-rational surface on a regular grid (z = 0 initially)."""
    # Control points on an (nu x nv) XY grid, z=0 unless specified.
    xs = np.linspace(0.0, float(nu - 1), nu)
    ys = np.linspace(0.0, float(nv - 1), nv)
    cp = np.zeros((nu, nv, 3), dtype=float)
    for i in range(nu):
        for j in range(nv):
            cp[i, j, :] = [xs[i], ys[j], 0.0]

    ku = np.array([0.0, 0.0, 1.0, 1.0]) if nu == 2 else np.array(
        [0.0] * 2 + list(np.linspace(0.0, 1.0, nu)) + [1.0] * 2
    )
    kv = np.array([0.0, 0.0, 1.0, 1.0]) if nv == 2 else np.array(
        [0.0] * 2 + list(np.linspace(0.0, 1.0, nv)) + [1.0] * 2
    )

    # Clamp to correct length: n+p+1 knots for n CPs and degree p.
    # Use uniform clamped knots with degree 1.
    p = 1
    ku = np.concatenate([[0.0] * (p + 1),
                         np.linspace(0.0, 1.0, nu - p + 1)[1:-1],
                         [1.0] * (p + 1)])
    kv = np.concatenate([[0.0] * (p + 1),
                         np.linspace(0.0, 1.0, nv - p + 1)[1:-1],
                         [1.0] * (p + 1)])

    return NurbsSurface(
        degree_u=p,
        degree_v=p,
        control_points=cp,
        knots_u=ku,
        knots_v=kv,
    )


def _make_3d_surface() -> NurbsSurface:
    """A simple degree-(1,1) bilinear patch with non-zero Z coordinates."""
    # 2x2 patch: corners at (0,0,0), (1,0,2), (0,1,3), (1,1,5)
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 3.0]],
        [[1.0, 0.0, 2.0], [1.0, 1.0, 5.0]],
    ], dtype=float)
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=ku, knots_v=kv,
    )


def _make_rational_surface() -> NurbsSurface:
    """Rational NURBS surface with non-unit weights."""
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
    ], dtype=float)
    weights = np.array([[1.0, 2.0], [2.0, 1.0]])
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=ku, knots_v=kv,
        weights=weights,
    )


# ---------------------------------------------------------------------------
# Test 1: Identity shear (all zero) — surface unchanged
# ---------------------------------------------------------------------------

def test_identity_shear_surface_unchanged():
    """Identity ShearMatrix should return control points identical to input."""
    srf = _make_simple_surface()
    shear = ShearMatrix()  # all defaults = 0.0
    result = apply_shear_offset(srf, shear)
    assert isinstance(result, SurfaceShearOffsetResult)
    np.testing.assert_allclose(
        result.sheared_surface.control_points,
        srf.control_points,
        atol=1e-15,
        err_msg="Identity shear must leave control points unchanged",
    )


# ---------------------------------------------------------------------------
# Test 2: Identity shear — zero displacements
# ---------------------------------------------------------------------------

def test_identity_shear_zero_displacement():
    """Identity shear must report zero max/mean displacement."""
    srf = _make_simple_surface()
    result = apply_shear_offset(srf, ShearMatrix())
    assert result.max_displacement_mm == pytest.approx(0.0, abs=1e-15)
    assert result.mean_displacement_mm == pytest.approx(0.0, abs=1e-15)


# ---------------------------------------------------------------------------
# Test 3: Identity shear — honest caveat mentions identity
# ---------------------------------------------------------------------------

def test_identity_shear_honest_caveat():
    """Identity shear's honest caveat should mention identity/unchanged."""
    result = apply_shear_offset(_make_simple_surface(), ShearMatrix())
    assert "identity" in result.honest_caveat.lower() or "zero" in result.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 4: Pure s_xy shear — x coords shifted by s_xy * y
# ---------------------------------------------------------------------------

def test_pure_s_xy_shear_x_shift():
    """s_xy=0.1 shifts x by 0.1 * y; y, z unchanged."""
    srf = _make_simple_surface(nu=3, nv=4)
    s = 0.1
    shear = ShearMatrix(s_xy=s)
    result = apply_shear_offset(srf, shear)
    cp_in = srf.control_points
    cp_out = result.sheared_surface.control_points
    for i in range(cp_in.shape[0]):
        for j in range(cp_in.shape[1]):
            x, y, z = cp_in[i, j]
            expected_x = x + s * y
            assert cp_out[i, j, 0] == pytest.approx(expected_x, abs=1e-12), (
                f"x mismatch at ({i},{j}): expected {expected_x}, got {cp_out[i,j,0]}"
            )
            assert cp_out[i, j, 1] == pytest.approx(y, abs=1e-12), "y should be unchanged"
            assert cp_out[i, j, 2] == pytest.approx(z, abs=1e-12), "z should be unchanged"


# ---------------------------------------------------------------------------
# Test 5: Pure s_yx shear — y coords shifted by s_yx * x
# ---------------------------------------------------------------------------

def test_pure_s_yx_shear_y_shift():
    """s_yx=0.2 shifts y by 0.2 * x; x, z unchanged."""
    srf = _make_3d_surface()
    s = 0.2
    shear = ShearMatrix(s_yx=s)
    result = apply_shear_offset(srf, shear)
    cp_in = srf.control_points
    cp_out = result.sheared_surface.control_points
    for i in range(cp_in.shape[0]):
        for j in range(cp_in.shape[1]):
            x, y, z = cp_in[i, j]
            assert cp_out[i, j, 0] == pytest.approx(x, abs=1e-12), "x should be unchanged"
            assert cp_out[i, j, 1] == pytest.approx(y + s * x, abs=1e-12)
            assert cp_out[i, j, 2] == pytest.approx(z, abs=1e-12), "z should be unchanged"


# ---------------------------------------------------------------------------
# Test 6: Pure s_zx shear — z shifted by s_zx * x
# ---------------------------------------------------------------------------

def test_pure_s_zx_shear_z_shift():
    """s_zx=0.3 shifts z by 0.3 * x; x, y unchanged."""
    srf = _make_3d_surface()
    s = 0.3
    shear = ShearMatrix(s_zx=s)
    result = apply_shear_offset(srf, shear)
    cp_in = srf.control_points
    cp_out = result.sheared_surface.control_points
    for i in range(cp_in.shape[0]):
        for j in range(cp_in.shape[1]):
            x, y, z = cp_in[i, j]
            assert cp_out[i, j, 0] == pytest.approx(x, abs=1e-12)
            assert cp_out[i, j, 1] == pytest.approx(y, abs=1e-12)
            assert cp_out[i, j, 2] == pytest.approx(z + s * x, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 7: Combined shears — superposition of all six
# ---------------------------------------------------------------------------

def test_combined_shear_superposition():
    """All six coefficients active simultaneously — superposition holds."""
    srf = _make_3d_surface()
    s_xy, s_xz = 0.1, 0.05
    s_yx, s_yz = 0.2, 0.07
    s_zx, s_zy = 0.15, 0.08
    shear = ShearMatrix(s_xy=s_xy, s_xz=s_xz, s_yx=s_yx, s_yz=s_yz,
                        s_zx=s_zx, s_zy=s_zy)
    result = apply_shear_offset(srf, shear)
    cp_in = srf.control_points
    cp_out = result.sheared_surface.control_points
    for i in range(cp_in.shape[0]):
        for j in range(cp_in.shape[1]):
            x, y, z = cp_in[i, j]
            exp_x = x + s_xy * y + s_xz * z
            exp_y = y + s_yx * x + s_yz * z
            exp_z = z + s_zx * x + s_zy * y
            np.testing.assert_allclose(cp_out[i, j], [exp_x, exp_y, exp_z], atol=1e-12)


# ---------------------------------------------------------------------------
# Test 8: Knots preserved exactly
# ---------------------------------------------------------------------------

def test_knots_preserved():
    """Knot vectors must be identical (copied) in the sheared surface."""
    srf = _make_simple_surface(nu=4, nv=3)
    result = apply_shear_offset(srf, ShearMatrix(s_xy=0.5))
    np.testing.assert_array_equal(result.sheared_surface.knots_u, srf.knots_u)
    np.testing.assert_array_equal(result.sheared_surface.knots_v, srf.knots_v)


# ---------------------------------------------------------------------------
# Test 9: Weights preserved exactly (rational surface)
# ---------------------------------------------------------------------------

def test_weights_preserved_rational():
    """Weights must be identical in the sheared surface for rational NURBS."""
    srf = _make_rational_surface()
    result = apply_shear_offset(srf, ShearMatrix(s_xz=0.1, s_zy=0.2))
    assert result.sheared_surface.weights is not None
    np.testing.assert_array_equal(result.sheared_surface.weights, srf.weights)


# ---------------------------------------------------------------------------
# Test 10: Weights None preserved (non-rational surface)
# ---------------------------------------------------------------------------

def test_weights_none_preserved():
    """Non-rational surface weights must remain None after shear."""
    srf = _make_simple_surface()
    result = apply_shear_offset(srf, ShearMatrix(s_yz=0.3))
    assert result.sheared_surface.weights is None


# ---------------------------------------------------------------------------
# Test 11: Max displacement formula
# ---------------------------------------------------------------------------

def test_max_displacement_formula():
    """max_displacement_mm must equal the max ||P' - P|| over all control points."""
    srf = _make_3d_surface()
    shear = ShearMatrix(s_xy=0.5, s_yz=0.3, s_zx=0.2)
    result = apply_shear_offset(srf, shear)
    cp_in = srf.control_points.reshape(-1, 3)
    cp_out = result.sheared_surface.control_points.reshape(-1, 3)
    expected_max = float(np.max(np.linalg.norm(cp_out - cp_in, axis=1)))
    assert result.max_displacement_mm == pytest.approx(expected_max, rel=1e-12)


# ---------------------------------------------------------------------------
# Test 12: Mean displacement formula
# ---------------------------------------------------------------------------

def test_mean_displacement_formula():
    """mean_displacement_mm must equal the mean ||P' - P|| over all control points."""
    srf = _make_3d_surface()
    shear = ShearMatrix(s_xy=0.5, s_yz=0.3, s_zx=0.2)
    result = apply_shear_offset(srf, shear)
    cp_in = srf.control_points.reshape(-1, 3)
    cp_out = result.sheared_surface.control_points.reshape(-1, 3)
    expected_mean = float(np.mean(np.linalg.norm(cp_out - cp_in, axis=1)))
    assert result.mean_displacement_mm == pytest.approx(expected_mean, rel=1e-12)


# ---------------------------------------------------------------------------
# Test 13: max_displacement >= mean_displacement
# ---------------------------------------------------------------------------

def test_max_ge_mean_displacement():
    """max displacement is always >= mean displacement."""
    srf = _make_simple_surface(nu=5, nv=5)
    shear = ShearMatrix(s_xy=0.3, s_xz=0.1, s_zy=0.2)
    result = apply_shear_offset(srf, shear)
    assert result.max_displacement_mm >= result.mean_displacement_mm - 1e-14


# ---------------------------------------------------------------------------
# Test 14: Result type and degree preserved
# ---------------------------------------------------------------------------

def test_result_type_and_degrees():
    """Output surface has correct type, degree_u, degree_v."""
    srf = _make_simple_surface(nu=3, nv=3)
    result = apply_shear_offset(srf, ShearMatrix(s_xy=0.1))
    out = result.sheared_surface
    assert isinstance(out, NurbsSurface)
    assert out.degree_u == srf.degree_u
    assert out.degree_v == srf.degree_v
    assert out.control_points.shape == srf.control_points.shape


# ---------------------------------------------------------------------------
# Test 15: ValueError for non-3D control points
# ---------------------------------------------------------------------------

def test_error_non_3d_control_points():
    """apply_shear_offset must raise ValueError for 2-D control points."""
    # Build a surface with 2-D control points (shape nu x nv x 2).
    cp = np.zeros((2, 2, 2), dtype=float)  # 2-D XY only
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    # NurbsSurface validates ndim==3 on the array, but shape[2]==2 != 3
    srf = NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                       knots_u=ku, knots_v=kv)
    with pytest.raises(ValueError, match="3"):
        apply_shear_offset(srf, ShearMatrix(s_xy=0.1))


# ---------------------------------------------------------------------------
# Test 16: ShearMatrix dataclass defaults
# ---------------------------------------------------------------------------

def test_shear_matrix_defaults():
    """ShearMatrix() default should have all coefficients == 0.0."""
    m = ShearMatrix()
    assert m.s_xy == 0.0
    assert m.s_xz == 0.0
    assert m.s_yx == 0.0
    assert m.s_yz == 0.0
    assert m.s_zx == 0.0
    assert m.s_zy == 0.0


# ---------------------------------------------------------------------------
# Test 17: Input surface not mutated
# ---------------------------------------------------------------------------

def test_input_surface_not_mutated():
    """apply_shear_offset must not modify the input surface's control points."""
    srf = _make_3d_surface()
    cp_orig = srf.control_points.copy()
    apply_shear_offset(srf, ShearMatrix(s_xy=0.5, s_yz=0.2))
    np.testing.assert_array_equal(srf.control_points, cp_orig)


# ---------------------------------------------------------------------------
# Test 18: Honest caveat mentions linear limit for non-identity shear
# ---------------------------------------------------------------------------

def test_non_identity_honest_caveat_mentions_linear():
    """Non-identity shear honest caveat must mention linear shear limitation."""
    result = apply_shear_offset(_make_3d_surface(), ShearMatrix(s_xy=0.1))
    lower = result.honest_caveat.lower()
    assert "linear" in lower or "uniform" in lower or "non-uniform" in lower


# ---------------------------------------------------------------------------
# Test 19: s_xz shear — x shifted by s_xz * z
# ---------------------------------------------------------------------------

def test_pure_s_xz_shear():
    """s_xz=0.4 shifts x by 0.4 * z; y, z unchanged."""
    srf = _make_3d_surface()
    s = 0.4
    result = apply_shear_offset(srf, ShearMatrix(s_xz=s))
    cp_in = srf.control_points
    cp_out = result.sheared_surface.control_points
    for i in range(cp_in.shape[0]):
        for j in range(cp_in.shape[1]):
            x, y, z = cp_in[i, j]
            assert cp_out[i, j, 0] == pytest.approx(x + s * z, abs=1e-12)
            assert cp_out[i, j, 1] == pytest.approx(y, abs=1e-12)
            assert cp_out[i, j, 2] == pytest.approx(z, abs=1e-12)


# ---------------------------------------------------------------------------
# Test 20: Negative shear coefficient
# ---------------------------------------------------------------------------

def test_negative_shear_coefficient():
    """Negative shear coefficient must correctly negate displacement."""
    srf = _make_3d_surface()
    s = -0.7
    result = apply_shear_offset(srf, ShearMatrix(s_zy=s))
    cp_in = srf.control_points
    cp_out = result.sheared_surface.control_points
    for i in range(cp_in.shape[0]):
        for j in range(cp_in.shape[1]):
            x, y, z = cp_in[i, j]
            assert cp_out[i, j, 0] == pytest.approx(x, abs=1e-12)
            assert cp_out[i, j, 1] == pytest.approx(y, abs=1e-12)
            assert cp_out[i, j, 2] == pytest.approx(z + s * y, abs=1e-12)
