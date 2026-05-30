"""Tests for NURBS iso-curve extraction (Piegl-Tiller §5.3).

Hermetic, pure-Python (numpy only).  Each test asserts a closed-form
analytic oracle:

1. Round-trip: C(t) == S(u0, t) within 1e-10 (u-iso and v-iso).
2. Bezier surface: iso-curve is a Bezier curve of correct degree.
3. Rational sphere octant: u-iso is an arc at correct latitude radius.
4. Closed (periodic-like) surface: iso-curve endpoints coincide.
5. Bilinear surface: iso-curves are degree-1 lines (closed-form check).
6. Boundary iso-curves match corner control points (clamped knot vectors).
7. extract_iso_grid returns the correct counts and types.
"""

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    surface_evaluate,
    de_boor,
    make_circle_nurbs,
)
from kerf_cad_core.geom.iso_curve_extract import (
    extract_iso_curve_u,
    extract_iso_curve_v,
    extract_iso_grid,
)


# ---------------------------------------------------------------------------
# Surface fixtures
# ---------------------------------------------------------------------------

def _bilinear_surface():
    """Degree (1,1) patch; closed-form S(u,v) = bilinear blend."""
    P00 = np.array([0.0, 0.0, 0.0])
    P10 = np.array([2.0, 0.0, 1.0])
    P01 = np.array([0.0, 3.0, -1.0])
    P11 = np.array([2.0, 3.0, 4.0])
    cps = np.array([[P00, P01], [P10, P11]])
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    srf = NurbsSurface(degree_u=1, degree_v=1, control_points=cps,
                       knots_u=ku, knots_v=kv)

    def closed(u, v):
        return ((1 - u) * (1 - v) * P00 + (1 - u) * v * P01
                + u * (1 - v) * P10 + u * v * P11)

    return srf, closed


def _biquadratic_surface():
    """Degree (2,2) surface with clamped knots on [0,1]."""
    cps = np.zeros((3, 3, 3))
    for i in range(3):
        for j in range(3):
            cps[i, j] = np.array([float(i), float(j), float(i * j) * 0.25])
    ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    srf = NurbsSurface(degree_u=2, degree_v=2, control_points=cps,
                       knots_u=ku, knots_v=kv)
    return srf


def _bezier_surface():
    """Degree (2,3) Bezier patch (all-unique clamped knots on [0,1]).
    iso-u has degree 3; iso-v has degree 2.
    """
    # 3 x 4 control points
    cps = np.zeros((3, 4, 3))
    for i in range(3):
        for j in range(4):
            cps[i, j] = np.array([float(i), float(j), float((i + 1) * (j + 1)) * 0.1])
    ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    srf = NurbsSurface(degree_u=2, degree_v=3, control_points=cps,
                       knots_u=ku, knots_v=kv)
    return srf


def _rational_sphere_octant(R=1.0):
    """One octant of a sphere as exact biquadratic rational NURBS.

    Parameterised over [0,1] x [0,1]; maps to latitude [90,0] x azimuth [0,90].
    """
    s2 = np.sqrt(2.0) / 2.0
    Pz = np.array([0.0, 0.0, R])
    Pxz = np.array([R, 0.0, R])
    Px = np.array([R, 0.0, 0.0])
    cps = np.zeros((3, 3, 3))
    w = np.zeros((3, 3))
    lat_pts = [Pz, Pxz, Px]
    lat_w = [1.0, s2, 1.0]
    lon_w = [1.0, s2, 1.0]
    for i, (lp, lw) in enumerate(zip(lat_pts, lat_w)):
        x_r = lp[0]
        z = lp[2]
        lon_pts = [
            np.array([x_r, 0.0, z]),
            np.array([x_r, x_r, z]),
            np.array([0.0, x_r, z]),
        ]
        for j, lpt in enumerate(lon_pts):
            cps[i, j] = lpt
            w[i, j] = lw * lon_w[j]
    ku = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    srf = NurbsSurface(degree_u=2, degree_v=2, control_points=cps,
                       knots_u=ku, knots_v=kv, weights=w)
    return srf, R


# ---------------------------------------------------------------------------
# 1.  Round-trip: C(t) == S(u0, t) within 1e-10
# ---------------------------------------------------------------------------

def test_roundtrip_u_iso_biquadratic():
    """U-iso-curve evaluates identically to surface at fixed u."""
    srf = _biquadratic_surface()
    for u0 in [0.0, 0.25, 0.5, 0.75, 1.0]:
        curve = extract_iso_curve_u(srf, u0)
        for t in np.linspace(0.0, 1.0, 15):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, u0, t)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0), (
                f"u-iso u={u0} t={t}: curve={c_pt} surface={s_pt}"
            )


def test_roundtrip_v_iso_biquadratic():
    """V-iso-curve evaluates identically to surface at fixed v."""
    srf = _biquadratic_surface()
    for v0 in [0.0, 0.25, 0.5, 0.75, 1.0]:
        curve = extract_iso_curve_v(srf, v0)
        for t in np.linspace(0.0, 1.0, 15):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, t, v0)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0), (
                f"v-iso v={v0} t={t}: curve={c_pt} surface={s_pt}"
            )


def test_roundtrip_u_iso_bilinear():
    """Round-trip on bilinear surface (degree 1 x 1)."""
    srf, closed = _bilinear_surface()
    for u0 in [0.0, 0.3, 0.7, 1.0]:
        curve = extract_iso_curve_u(srf, u0)
        for t in np.linspace(0.0, 1.0, 11):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, u0, t)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0)


def test_roundtrip_v_iso_bilinear():
    """Round-trip on bilinear surface (degree 1 x 1)."""
    srf, closed = _bilinear_surface()
    for v0 in [0.0, 0.3, 0.7, 1.0]:
        curve = extract_iso_curve_v(srf, v0)
        for t in np.linspace(0.0, 1.0, 11):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, t, v0)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0)


# ---------------------------------------------------------------------------
# 2.  Bezier surface: iso-curve is a Bezier of the correct degree
# ---------------------------------------------------------------------------

def test_bezier_surface_u_iso_degree():
    """U-iso of a (2,3) Bezier surface has degree 3."""
    srf = _bezier_surface()
    curve = extract_iso_curve_u(srf, 0.5)
    assert curve.degree == 3


def test_bezier_surface_v_iso_degree():
    """V-iso of a (2,3) Bezier surface has degree 2."""
    srf = _bezier_surface()
    curve = extract_iso_curve_v(srf, 0.5)
    assert curve.degree == 2


def test_bezier_surface_u_iso_is_bezier():
    """U-iso of a Bezier surface has a clamped (Bezier) knot vector."""
    srf = _bezier_surface()
    # degree_v = 3, so iso has degree 3 and should have knot vector [0,0,0,0,1,1,1,1]
    curve = extract_iso_curve_u(srf, 0.5)
    expected_k = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    assert np.allclose(curve.knots, expected_k, atol=1e-14)
    # Should have exactly 4 control points (degree+1 for single-segment Bezier)
    assert curve.num_control_points == 4


def test_bezier_surface_u_iso_roundtrip():
    """Round-trip for Bezier surface iso-curve."""
    srf = _bezier_surface()
    for u0 in [0.0, 0.5, 1.0]:
        curve = extract_iso_curve_u(srf, u0)
        for t in np.linspace(0.0, 1.0, 13):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, u0, t)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0)


# ---------------------------------------------------------------------------
# 3.  Rational sphere octant: u-iso is arc at correct latitude
# ---------------------------------------------------------------------------

def test_sphere_u_iso_radius():
    """U-iso at u=0.5 of sphere octant lies on sphere surface (||pt|| = R)."""
    srf, R = _rational_sphere_octant(R=2.0)
    curve = extract_iso_curve_u(srf, 0.5)
    radii = []
    for t in np.linspace(0.0, 1.0, 25):
        pt = de_boor(curve, t)
        radii.append(np.linalg.norm(pt))
    radii = np.array(radii)
    # All points on sphere octant should have ||pt|| = R
    assert np.allclose(radii, R, atol=1e-9), (
        f"sphere u-iso max radius deviation {np.max(np.abs(radii - R)):.2e}"
    )


def test_sphere_u_iso_radius_variance():
    """Radius variance along sphere u-iso is < 1e-9 (great-circle quality)."""
    srf, R = _rational_sphere_octant(R=1.0)
    curve = extract_iso_curve_u(srf, 0.5)
    radii = np.array([np.linalg.norm(de_boor(curve, t))
                      for t in np.linspace(0.0, 1.0, 50)])
    assert np.var(radii) < 1e-9, f"radius variance {np.var(radii):.3e}"


def test_sphere_v_iso_roundtrip():
    """V-iso of rational sphere octant satisfies round-trip."""
    srf, R = _rational_sphere_octant(R=1.5)
    for v0 in [0.0, 0.5, 1.0]:
        curve = extract_iso_curve_v(srf, v0)
        for t in np.linspace(0.0, 1.0, 20):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, t, v0)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0)


def test_sphere_u_iso_roundtrip():
    """U-iso of rational sphere octant satisfies round-trip."""
    srf, R = _rational_sphere_octant(R=1.0)
    for u0 in [0.0, 0.25, 0.5, 0.75, 1.0]:
        curve = extract_iso_curve_u(srf, u0)
        for t in np.linspace(0.0, 1.0, 20):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, u0, t)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0), (
                f"sphere u-iso u={u0} t={t}: {np.linalg.norm(c_pt - s_pt):.3e}"
            )


# ---------------------------------------------------------------------------
# 4.  Closed surface: iso-curve endpoints coincide
# ---------------------------------------------------------------------------

def _closed_cylindrical_surface():
    """Exact cylinder using a rational quadratic full circle in v + linear in u.

    make_circle_nurbs returns 3D (XYZ) control points in the XY plane (z=0).
    We extrude along z to get the cylinder.
    """
    circle = make_circle_nurbs(center=np.array([0.0, 0.0, 0.0]), radius=1.0)

    n_v = circle.num_control_points
    dv = circle.degree
    kv = circle.knots
    w_circ = circle.weights
    cps_circ = circle.control_points  # (n_v, 3) - all z=0

    # Two rows: z=0 (bottom) and z=1 (top)
    cps = np.zeros((2, n_v, 3))
    cps[0, :, :] = cps_circ
    cps[0, :, 2] = 0.0
    cps[1, :, :] = cps_circ
    cps[1, :, 2] = 1.0

    weights = np.ones((2, n_v))
    if w_circ is not None:
        weights[0, :] = w_circ
        weights[1, :] = w_circ

    ku = np.array([0.0, 0.0, 1.0, 1.0])
    srf = NurbsSurface(
        degree_u=1,
        degree_v=dv,
        control_points=cps,
        knots_u=ku,
        knots_v=kv,
        weights=weights,
    )
    return srf


def test_closed_surface_v_iso_closes():
    """U-iso of closed cylinder is a closed curve (endpoints coincide)."""
    srf = _closed_cylindrical_surface()
    v0 = float(srf.knots_v[0])
    v1 = float(srf.knots_v[-1])
    curve = extract_iso_curve_u(srf, 0.5)
    p_start = de_boor(curve, v0)
    p_end = de_boor(curve, v1)
    assert np.allclose(p_start, p_end, atol=1e-10), (
        f"closed curve endpoints differ: start={p_start} end={p_end}"
    )


def test_closed_surface_u_iso_closure_roundtrip():
    """U-iso at any u of closed cylinder lies on the circle."""
    srf = _closed_cylindrical_surface()
    for u0 in [0.0, 0.5, 1.0]:
        curve = extract_iso_curve_u(srf, u0)
        radii = []
        for t in np.linspace(float(srf.knots_v[0]), float(srf.knots_v[-1]), 30):
            pt = de_boor(curve, t)
            radii.append(np.linalg.norm(pt[:2]))
        assert np.allclose(radii, 1.0, atol=1e-9), (
            f"cylinder u-iso u={u0} max radius error {max(abs(r - 1.0) for r in radii):.3e}"
        )


# ---------------------------------------------------------------------------
# 5.  Bilinear surface: iso-curves are degree-1 lines (closed-form check)
# ---------------------------------------------------------------------------

def test_bilinear_u_iso_is_line():
    """U-iso of bilinear surface: degree=1, 2 CPs, matches analytical line."""
    srf, closed = _bilinear_surface()
    u0 = 0.4
    curve = extract_iso_curve_u(srf, u0)
    assert curve.degree == 1
    assert curve.num_control_points == 2
    for t in np.linspace(0.0, 1.0, 11):
        c_pt = de_boor(curve, t)
        oracle = closed(u0, t)
        assert np.allclose(c_pt, oracle, atol=1e-12)


def test_bilinear_v_iso_is_line():
    """V-iso of bilinear surface: degree=1, 2 CPs, matches analytical line."""
    srf, closed = _bilinear_surface()
    v0 = 0.6
    curve = extract_iso_curve_v(srf, v0)
    assert curve.degree == 1
    assert curve.num_control_points == 2
    for t in np.linspace(0.0, 1.0, 11):
        c_pt = de_boor(curve, t)
        oracle = closed(t, v0)
        assert np.allclose(c_pt, oracle, atol=1e-12)


# ---------------------------------------------------------------------------
# 6.  Boundary iso-curves match corner control points (clamped KV)
# ---------------------------------------------------------------------------

def test_boundary_u_iso_corner_points():
    """U-iso at u=0 and u=1 of biquadratic surface: endpoints match CP corners."""
    srf = _biquadratic_surface()
    for u_boundary in [0.0, 1.0]:
        curve = extract_iso_curve_u(srf, u_boundary)
        row_idx = 0 if u_boundary == 0.0 else (srf.num_control_points_u - 1)
        pt_start = de_boor(curve, 0.0)
        assert np.allclose(pt_start, srf.control_points[row_idx, 0], atol=1e-10), (
            f"boundary u={u_boundary} start mismatch: {pt_start} vs {srf.control_points[row_idx, 0]}"
        )
        pt_end = de_boor(curve, 1.0)
        assert np.allclose(pt_end, srf.control_points[row_idx, -1], atol=1e-10), (
            f"boundary u={u_boundary} end mismatch: {pt_end} vs {srf.control_points[row_idx, -1]}"
        )


# ---------------------------------------------------------------------------
# 7.  extract_iso_grid: correct counts and types
# ---------------------------------------------------------------------------

def test_iso_grid_counts():
    """extract_iso_grid returns exactly u_count and v_count curves."""
    srf = _biquadratic_surface()
    grid = extract_iso_grid(srf, u_count=4, v_count=5)
    assert len(grid["u_curves"]) == 4
    assert len(grid["v_curves"]) == 5


def test_iso_grid_types():
    """extract_iso_grid entries are NurbsCurve instances."""
    srf = _biquadratic_surface()
    grid = extract_iso_grid(srf, u_count=3, v_count=3)
    for c in grid["u_curves"] + grid["v_curves"]:
        assert isinstance(c, NurbsCurve)


def test_iso_grid_u_curves_roundtrip():
    """All u_curves in grid satisfy round-trip at their extracted parameter."""
    srf = _biquadratic_surface()
    n_u = 5
    u_params = np.linspace(0.0, 1.0, n_u)
    grid = extract_iso_grid(srf, u_count=n_u, v_count=3)
    for u0, curve in zip(u_params, grid["u_curves"]):
        for t in np.linspace(0.0, 1.0, 7):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, u0, t)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0)


def test_iso_grid_v_curves_roundtrip():
    """All v_curves in grid satisfy round-trip at their extracted parameter."""
    srf = _biquadratic_surface()
    n_v = 4
    v_params = np.linspace(0.0, 1.0, n_v)
    grid = extract_iso_grid(srf, u_count=3, v_count=n_v)
    for v0, curve in zip(v_params, grid["v_curves"]):
        for t in np.linspace(0.0, 1.0, 7):
            c_pt = de_boor(curve, t)
            s_pt = surface_evaluate(srf, t, v0)
            assert np.allclose(c_pt, s_pt, atol=1e-10, rtol=0)


# ---------------------------------------------------------------------------
# 8.  Error handling
# ---------------------------------------------------------------------------

def test_out_of_range_u_raises():
    srf = _biquadratic_surface()
    with pytest.raises(ValueError, match="out of knot range"):
        extract_iso_curve_u(srf, 1.5)


def test_out_of_range_v_raises():
    srf = _biquadratic_surface()
    with pytest.raises(ValueError, match="out of knot range"):
        extract_iso_curve_v(srf, -0.1)


def test_iso_grid_bad_count_raises():
    srf = _biquadratic_surface()
    with pytest.raises(ValueError):
        extract_iso_grid(srf, u_count=0, v_count=3)
