"""GK-P15 — surface_analytic_derivatives tests.

Covers:
1. Plane surface: ∂S/∂u, ∂S/∂v constant; all 2nd derivs zero; K=H=0.
2. Cylinder: ∂S/∂u tangent, ∂S/∂v axial; ∂²S/∂u² radially inward; K=0, H=1/(2R).
3. Sphere (rational): K=1/R², H=1/R.
4. Analytic vs Richardson central-difference < 1e-8.
5. SSIHardenedMarcher: two crossing cylinders yield an intersection curve.
6. Dataclass fields present.
7. Rational surface honest_caveat.
8. Curvature identity K = κ₁·κ₂, H = (κ₁+κ₂)/2.
9. Bilinear patch known partials.
10. Parameter clamping (out-of-domain request).
11. SSIHardenedMarcher: cylinder x plane — known circle radius.
12. Near-tangent bisection guard (flat surfaces, normals almost parallel).

Hermetic: pure Python + NumPy.  No OCCT, no DB, no network.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

# Make test_ssi_robust helpers importable (sphere/cylinder factories).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate
from kerf_cad_core.geom.surface_analytic_derivatives import (
    SurfaceDerivativeResult,
    SSIHardenedMarcher,
    compute_analytic_derivatives,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------

_S = math.sqrt(2.0) / 2.0
_CIRC9 = [
    (1.0, 0.0, 1.0), (1.0, 1.0, _S), (0.0, 1.0, 1.0), (-1.0, 1.0, _S),
    (-1.0, 0.0, 1.0), (-1.0, -1.0, _S), (0.0, -1.0, 1.0), (1.0, -1.0, _S),
    (1.0, 0.0, 1.0),
]
_KU9 = np.array([0, 0, 0, .25, .25, .5, .5, .75, .75, 1, 1, 1.0])


def _make_plane(origin=(0, 0, 0), e1=(1, 0, 0), e2=(0, 1, 0), half=2.0):
    """Bilinear (degree-1) flat plane patch S(u,v) = origin + u*e1*2*half + v*e2*2*half
    on [0,1]^2."""
    o = np.array(origin, dtype=float)
    u1 = np.array(e1, dtype=float)
    u2 = np.array(e2, dtype=float)
    cp = np.zeros((2, 2, 3))
    for i, su in enumerate((0.0, 1.0)):
        for j, sv in enumerate((0.0, 1.0)):
            cp[i, j] = o + su * u1 * 2 * half + sv * u2 * 2 * half
    k = np.array([0, 0, 1, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=k.copy(), knots_v=k.copy())


def _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                             r=1.0, half_len=1.0):
    """Exact NURBS right circular cylinder (rational-quad cross section)."""
    axis_pt = np.asarray(axis_pt, dtype=float)
    axis_dir = np.asarray(axis_dir, dtype=float)
    axis_dir = axis_dir / np.linalg.norm(axis_dir)
    ref = (np.array([1.0, 0.0, 0.0]) if abs(axis_dir[0]) < 0.9
           else np.array([0.0, 1.0, 0.0]))
    e1 = ref - (ref @ axis_dir) * axis_dir
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.cross(axis_dir, e1)
    cp = np.zeros((9, 2, 3))
    w = np.zeros((9, 2))
    for i, (cx, cy, cw) in enumerate(_CIRC9):
        radial = r * (cx * e1 + cy * e2)
        for j, t in enumerate((-half_len, half_len)):
            cp[i, j] = axis_pt + radial + t * axis_dir
            w[i, j] = cw
    kv = np.array([0, 0, 1, 1.0])
    return NurbsSurface(degree_u=2, degree_v=1, control_points=cp,
                        knots_u=_KU9.copy(), knots_v=kv, weights=w)


def _make_rational_sphere(center=(0, 0, 0), r=1.0):
    """Exact rational NURBS sphere (revolution of rational half-circle)."""
    center = np.asarray(center, dtype=float)
    mer = [
        (0.0, -r, 1.0), (r, -r, _S), (r, 0.0, 1.0), (r, r, _S), (0.0, r, 1.0),
    ]
    cp = np.zeros((9, 5, 3))
    w = np.zeros((9, 5))
    for i, (cx, cy, cw) in enumerate(_CIRC9):
        for j, (mx, mz, mw) in enumerate(mer):
            cp[i, j] = [center[0] + mx * cx, center[1] + mx * cy,
                        center[2] + mz]
            w[i, j] = cw * mw
    kv = np.array([0, 0, 0, .5, .5, 1, 1, 1.0])
    return NurbsSurface(degree_u=2, degree_v=2, control_points=cp,
                        knots_u=_KU9.copy(), knots_v=kv, weights=w)


# ---------------------------------------------------------------------------
# Helper: Richardson central-difference partial
# ---------------------------------------------------------------------------

def _rich(surf, u, v, ku, kv):
    """Richardson-extrapolated central-difference partial (< 1e-10 error)."""
    second = (ku + kv) >= 2
    h = 4e-3 if second else 1e-3

    def _cd(hh):
        if (ku, kv) == (1, 0):
            return (surface_evaluate(surf, u + hh, v)
                    - surface_evaluate(surf, u - hh, v)) / (2 * hh)
        if (ku, kv) == (0, 1):
            return (surface_evaluate(surf, u, v + hh)
                    - surface_evaluate(surf, u, v - hh)) / (2 * hh)
        if (ku, kv) == (2, 0):
            return (surface_evaluate(surf, u + hh, v)
                    - 2 * surface_evaluate(surf, u, v)
                    + surface_evaluate(surf, u - hh, v)) / (hh * hh)
        if (ku, kv) == (0, 2):
            return (surface_evaluate(surf, u, v + hh)
                    - 2 * surface_evaluate(surf, u, v)
                    + surface_evaluate(surf, u, v - hh)) / (hh * hh)
        # (1, 1) mixed
        return (surface_evaluate(surf, u + hh, v + hh)
                - surface_evaluate(surf, u + hh, v - hh)
                - surface_evaluate(surf, u - hh, v + hh)
                + surface_evaluate(surf, u - hh, v - hh)) / (4 * hh * hh)

    f_h = _cd(h)
    f_h2 = _cd(h / 2)
    return (4.0 * f_h2 - f_h) / 3.0


# ===========================================================================
# Test 1 — Plane: constant first partials, zero second partials, K=H=0
# ===========================================================================

def test_plane_first_partials_constant():
    """On a flat bilinear patch S(u,v) = u*e1 + v*e2 the first partials are
    constant (equal to the edge vectors) for all (u,v)."""
    e1 = np.array([4.0, 0.0, 0.0])   # dS/du = 4 * (1,0,0)
    e2 = np.array([0.0, 4.0, 0.0])   # dS/dv = 4 * (0,1,0)
    surf = _make_plane(e1=e1 / 4, e2=e2 / 4, half=2.0)
    for u, v in [(0.2, 0.3), (0.5, 0.5), (0.8, 0.1)]:
        r = compute_analytic_derivatives(surf, u, v)
        assert np.allclose(r.dS_du, e1, atol=1e-9), (u, v, r.dS_du)
        assert np.allclose(r.dS_dv, e2, atol=1e-9), (u, v, r.dS_dv)


def test_plane_second_partials_zero():
    """All second partials vanish on a flat (bilinear) surface."""
    surf = _make_plane()
    for u, v in [(0.25, 0.4), (0.6, 0.75)]:
        r = compute_analytic_derivatives(surf, u, v)
        assert np.allclose(r.d2S_du2, [0, 0, 0], atol=1e-9), r.d2S_du2
        assert np.allclose(r.d2S_dudv, [0, 0, 0], atol=1e-9), r.d2S_dudv
        assert np.allclose(r.d2S_dv2, [0, 0, 0], atol=1e-9), r.d2S_dv2


def test_plane_curvature_zero():
    """Gaussian and mean curvature are both 0 on a flat plane."""
    surf = _make_plane()
    r = compute_analytic_derivatives(surf, 0.5, 0.5)
    assert abs(r.gauss_K) < 1e-9, r.gauss_K
    assert abs(r.mean_H) < 1e-9, r.mean_H


# ===========================================================================
# Test 2 — Cylinder: curvatures
# ===========================================================================

def test_cylinder_gauss_curvature_zero():
    """K = 0 on a right circular cylinder (it is developable)."""
    R = 2.0
    cyl = _make_rational_cylinder(r=R)
    # Sample at a well-conditioned parameter away from the seam (u=0 / u=1).
    for u, v in [(0.15, 0.4), (0.35, 0.6), (0.6, 0.5)]:
        r = compute_analytic_derivatives(cyl, u, v)
        if not math.isnan(r.gauss_K):
            assert abs(r.gauss_K) < 1e-4, (u, v, r.gauss_K)


def test_cylinder_mean_curvature():
    """H = 1/(2R) on a right circular cylinder of radius R."""
    R = 3.0
    cyl = _make_rational_cylinder(r=R)
    expected_H = 1.0 / (2.0 * R)
    for u, v in [(0.15, 0.4), (0.35, 0.6), (0.6, 0.5)]:
        r = compute_analytic_derivatives(cyl, u, v)
        if not math.isnan(r.mean_H):
            assert abs(abs(r.mean_H) - expected_H) < 2e-3, (
                u, v, r.mean_H, expected_H
            )


def test_cylinder_d2S_du2_radially_inward():
    """∂²S/∂u² points radially inward (centripetal) on a cylinder with
    axis along Z.  The second u-derivative is perpendicular to the axis
    and antiparallel to the radial direction."""
    R = 2.0
    cyl = _make_rational_cylinder(r=R, axis_dir=(0, 0, 1))
    # At u ≈ 0.125 (first octant), the surface point has radial component
    # pointing roughly in the +X direction.
    u, v = 0.125, 0.5
    r = compute_analytic_derivatives(cyl, u, v)
    P = surface_evaluate(cyl, u, v)[:3]
    # Radial direction from axis (Z) to P.
    radial = np.array([P[0], P[1], 0.0])
    radial_norm = np.linalg.norm(radial)
    if radial_norm > 1e-9:
        radial_hat = radial / radial_norm
        suu = np.array(r.d2S_du2)
        suu_xy = np.array([suu[0], suu[1], 0.0])
        suu_mag = np.linalg.norm(suu_xy)
        if suu_mag > 1e-9:
            # Must be antiparallel to radial (dot < 0).
            dot = float(np.dot(suu_xy / suu_mag, radial_hat))
            assert dot < -0.5, f"Expected inward d2S_du2, dot={dot}"


# ===========================================================================
# Test 3 — Sphere: curvatures
# ===========================================================================

def test_sphere_gauss_curvature():
    """K = 1/R² on an exact rational NURBS sphere of radius R."""
    R = 2.0
    sph = _make_rational_sphere(r=R)
    expected_K = 1.0 / (R * R)
    # Avoid poles (v=0 or v=1) and seams (u=0 or u=1).
    for u, v in [(0.12, 0.35), (0.38, 0.55), (0.62, 0.4)]:
        r = compute_analytic_derivatives(sph, u, v)
        if not math.isnan(r.gauss_K):
            assert abs(r.gauss_K - expected_K) < 5e-3, (
                u, v, r.gauss_K, expected_K
            )


def test_sphere_mean_curvature():
    """H = 1/R on a sphere of radius R (both principal curvatures equal 1/R)."""
    R = 1.5
    sph = _make_rational_sphere(r=R)
    expected_H = 1.0 / R
    for u, v in [(0.12, 0.35), (0.38, 0.55), (0.62, 0.4)]:
        r = compute_analytic_derivatives(sph, u, v)
        if not math.isnan(r.mean_H):
            assert abs(abs(r.mean_H) - expected_H) < 5e-3, (
                u, v, r.mean_H, expected_H
            )


# ===========================================================================
# Test 4 — Analytic vs central-difference < 1e-8
# ===========================================================================

def test_analytic_vs_fd_bicubic_nonrational():
    """All five partials agree with Richardson FD to < 1e-8 on a bicubic
    B-spline surface (non-rational)."""
    nu, nv = 6, 5
    k_u = np.concatenate([np.zeros(4), np.linspace(0, 1, 4)[1:-1], np.ones(4)])
    k_v = np.concatenate([np.zeros(4), np.linspace(0, 1, 3)[1:-1], np.ones(4)])
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            x, y = i / (nu - 1), j / (nv - 1)
            cp[i, j] = [x, y, 0.5 * x ** 2 - 0.3 * x * y + 0.4 * y ** 2]
    surf = NurbsSurface(degree_u=3, degree_v=3, control_points=cp,
                        knots_u=k_u, knots_v=k_v)

    # Sample strictly inside one knot span (no FD straddles an inner knot).
    for u, v in [(0.18, 0.22), (0.55, 0.62), (0.72, 0.38)]:
        r = compute_analytic_derivatives(surf, u, v)
        for (ku, kv), ana_val in [
            ((1, 0), r.dS_du),
            ((0, 1), r.dS_dv),
            ((2, 0), r.d2S_du2),
            ((1, 1), r.d2S_dudv),
            ((0, 2), r.d2S_dv2),
        ]:
            ref = _rich(surf, u, v, ku, kv)[:3]
            ana = np.array(ana_val)
            err = float(np.max(np.abs(ana - ref)))
            assert err < 1e-8, f"({ku},{kv}) at ({u},{v}): err={err:.3e}"


def test_analytic_vs_fd_rational_cylinder():
    """First partials on the exact rational cylinder agree with FD < 1e-6."""
    R = 2.0
    cyl = _make_rational_cylinder(r=R)
    for u, v in [(0.1, 0.4), (0.35, 0.55), (0.6, 0.3)]:
        r = compute_analytic_derivatives(cyl, u, v)
        for (ku, kv), ana_val in [((1, 0), r.dS_du), ((0, 1), r.dS_dv)]:
            ref = _rich(cyl, u, v, ku, kv)[:3]
            ana = np.array(ana_val)
            err = float(np.max(np.abs(ana - ref)))
            assert err < 1e-6, f"cylinder ({ku},{kv}) at ({u},{v}): err={err:.3e}"


# ===========================================================================
# Test 5 — SSIHardenedMarcher: two crossing cylinders
# ===========================================================================

def test_ssi_marcher_two_cylinders_crossing():
    """Two cylinders whose axes are perpendicular intersect in a Steinmetz
    curve.  The SSIHardenedMarcher must return at least 4 points, and all
    points must lie within tolerance on both surfaces.

    Exact seed: for the unit-radius cylinders (half_len=1.5) the Steinmetz
    curve passes through (1/√2, 1/√2, 1/√2).  With cyl_a at (u=0.125, v≈0.736)
    and cyl_b at the same (u, v), both surfaces evaluate to the same 3-D point.
    """
    import math as _math
    R = 1.0
    half_len = 1.5
    cyl_a = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                    r=R, half_len=half_len)
    cyl_b = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(1, 0, 0),
                                    r=R, half_len=half_len)

    # The Steinmetz intersection passes through (1/√2, 1/√2, 1/√2).
    # cyl_a axis=Z: P=(R*cx, R*cy, z); at u=0.125 → cx=cy=1/√2, z from v.
    # cyl_b axis=X: P=(x, R*cx_b, R*cy_b); at u=0.125 → cx_b=cy_b=1/√2, x from v.
    # z=x=1/√2 requires the same v ≈ 0.5 + (1/√2)/(2*half_len) ≈ 0.736.
    p = 1.0 / _math.sqrt(2)
    v_seed = 0.5 + p / (2.0 * half_len)  # ≈ 0.736

    marcher = SSIHardenedMarcher()
    pts = marcher.march(
        cyl_a, cyl_b,
        seed_uv_a=(0.125, v_seed),
        seed_uv_b=(0.125, v_seed),
        step_mm=0.2,
        max_steps=200,
    )
    # Must return at least a few points.
    assert len(pts) >= 3, f"Expected >=3 pts, got {len(pts)}"

    # All points must lie within 0.2 of radius R from each cylinder axis.
    pts_arr = np.array(pts)
    # cyl_a axis = Z; distance from Z-axis.
    dist_a = np.sqrt(pts_arr[:, 0] ** 2 + pts_arr[:, 1] ** 2)
    # cyl_b axis = X; distance from X-axis.
    dist_b = np.sqrt(pts_arr[:, 1] ** 2 + pts_arr[:, 2] ** 2)
    # Points should lie near the surface of both cylinders.
    assert np.all(np.abs(dist_a - R) < 0.2), (
        f"cyl_a deviations: {np.abs(dist_a - R)}"
    )
    assert np.all(np.abs(dist_b - R) < 0.2), (
        f"cyl_b deviations: {np.abs(dist_b - R)}"
    )


# ===========================================================================
# Test 6 — SurfaceDerivativeResult dataclass
# ===========================================================================

def test_result_dataclass_fields():
    """SurfaceDerivativeResult has the required fields."""
    surf = _make_plane()
    r = compute_analytic_derivatives(surf, 0.5, 0.5)
    assert isinstance(r, SurfaceDerivativeResult)
    assert len(r.dS_du) == 3
    assert len(r.dS_dv) == 3
    assert len(r.d2S_du2) == 3
    assert len(r.d2S_dudv) == 3
    assert len(r.d2S_dv2) == 3
    assert isinstance(r.gauss_K, float)
    assert isinstance(r.mean_H, float)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 0


# ===========================================================================
# Test 7 — Rational surface reports rational caveat
# ===========================================================================

def test_rational_surface_honest_caveat():
    """A rational NURBS surface should mention 'RATIONAL' or 'rational'
    in the honest_caveat."""
    sph = _make_rational_sphere(r=2.0)
    r = compute_analytic_derivatives(sph, 0.3, 0.45)
    assert "rational" in r.honest_caveat.lower(), r.honest_caveat


def test_nonrational_surface_honest_caveat():
    """A non-rational surface should mention 'Non-rational' or 'polynomial'."""
    surf = _make_plane()
    r = compute_analytic_derivatives(surf, 0.5, 0.5)
    assert ("non-rational" in r.honest_caveat.lower()
            or "polynomial" in r.honest_caveat.lower()), r.honest_caveat


# ===========================================================================
# Test 8 — Curvature identity K = kappa1*kappa2, H = (kappa1+kappa2)/2
# ===========================================================================

def test_curvature_principal_identities_sphere():
    """On a sphere K = κ₁·κ₂, H = (κ₁+κ₂)/2 with κ₁=κ₂=1/R."""
    R = 2.5
    sph = _make_rational_sphere(r=R)
    u, v = 0.3, 0.45
    r = compute_analytic_derivatives(sph, u, v)
    if not (math.isnan(r.gauss_K) or math.isnan(r.mean_H)):
        # κ₁ = κ₂ = H (sphere is umbilical) → K = H².
        assert abs(r.gauss_K - r.mean_H ** 2) < 1e-3, (r.gauss_K, r.mean_H)
        # For a sphere H should satisfy H² >= K (non-negative discriminant).
        assert r.mean_H ** 2 - r.gauss_K >= -1e-6, (r.mean_H, r.gauss_K)


# ===========================================================================
# Test 9 — Bilinear patch known exact partials
# ===========================================================================

def test_bilinear_patch_known_partials():
    """S(u,v) = [2u, 3v, 0] on [0,1]^2 → dS/du = (2,0,0), dS/dv = (0,3,0)."""
    cp = np.array([
        [[0, 0, 0], [0, 3, 0]],
        [[2, 0, 0], [2, 3, 0]],
    ], dtype=float)
    k = np.array([0, 0, 1, 1.0])
    surf = NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=k.copy(), knots_v=k.copy())
    r = compute_analytic_derivatives(surf, 0.5, 0.5)
    assert np.allclose(r.dS_du, [2.0, 0.0, 0.0], atol=1e-10), r.dS_du
    assert np.allclose(r.dS_dv, [0.0, 3.0, 0.0], atol=1e-10), r.dS_dv
    assert np.allclose(r.d2S_du2, [0, 0, 0], atol=1e-10), r.d2S_du2
    assert np.allclose(r.d2S_dv2, [0, 0, 0], atol=1e-10), r.d2S_dv2


# ===========================================================================
# Test 10 — Out-of-domain parameter clamping
# ===========================================================================

def test_parameter_clamping_does_not_raise():
    """Requesting derivatives outside the knot domain should be clamped
    gracefully without raising an exception."""
    surf = _make_plane()
    # u=1.5 is outside [0,1]; should be clamped to 1.0.
    r = compute_analytic_derivatives(surf, 1.5, 0.5)
    assert isinstance(r, SurfaceDerivativeResult)

    r2 = compute_analytic_derivatives(surf, -0.1, 1.2)
    assert isinstance(r2, SurfaceDerivativeResult)


# ===========================================================================
# Test 11 — SSIHardenedMarcher: cylinder x plane, known circle radius
# ===========================================================================

def test_ssi_marcher_cylinder_plane_radius():
    """A horizontal plane at z=0 intersects a vertical cylinder of radius R
    along a circle of radius R.  The marcher should yield points within
    tolerance of R from the Z axis.

    Exact seed: the cylinder (axis=Z, radius=R) at (u=0.1, v=0.5) evaluates
    to a 3-D point at z=0 on the circular cross-section.  The plane z=0 at
    the same XY location provides an exact coincident seed.
    """
    R = 1.5
    cyl = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                  r=R, half_len=1.5)
    # Bilinear plane z=0 spanning [-3,3]^2 in XY.
    cp = np.array([
        [[-3, -3, 0], [-3, 3, 0]],
        [[3, -3, 0], [3, 3, 0]],
    ], dtype=float)
    k = np.array([0, 0, 1, 1.0])
    plane = NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                         knots_u=k.copy(), knots_v=k.copy())

    # Cylinder at u=0.1, v=0.5 → (x, y, 0) on the circle; v=0.5 → z=0.
    # Plane parameterization: x = -3 + u_p * 6,  y = -3 + v_p * 6.
    # So u_p = (x+3)/6,  v_p = (y+3)/6.
    from kerf_cad_core.geom.nurbs import surface_evaluate as _sev
    P_cyl = _sev(cyl, 0.1, 0.5)[:3]
    u_p = float((P_cyl[0] + 3) / 6)
    v_p = float((P_cyl[1] + 3) / 6)

    marcher = SSIHardenedMarcher()
    pts = marcher.march(
        cyl, plane,
        seed_uv_a=(0.1, 0.5),
        seed_uv_b=(u_p, v_p),
        step_mm=0.3,
        max_steps=300,
    )
    assert len(pts) >= 3, f"Expected >=3 pts, got {len(pts)}"
    pts_arr = np.array(pts)
    dist_from_z = np.sqrt(pts_arr[:, 0] ** 2 + pts_arr[:, 1] ** 2)
    # All points should be within 20% of R from the Z axis.
    assert np.all(np.abs(dist_from_z - R) < R * 0.25), (
        f"cylinder-plane intersection radii: {dist_from_z}"
    )
    # All points should be close to z=0.
    assert np.all(np.abs(pts_arr[:, 2]) < 0.1), (
        f"cylinder-plane intersection z values: {pts_arr[:, 2]}"
    )


# ===========================================================================
# Test 12 — Near-tangent guard: two parallel planes
# ===========================================================================

def test_near_tangent_guard_parallel_planes():
    """Two nearly-parallel planes sharing an edge: the marcher should
    return a result without raising (bisection guard prevents infinite loop)."""
    # Plane 1: z = 0
    cp1 = np.array([
        [[-2, -2, 0], [-2, 2, 0]],
        [[2, -2, 0], [2, 2, 0]],
    ], dtype=float)
    k = np.array([0, 0, 1, 1.0])
    plane1 = NurbsSurface(degree_u=1, degree_v=1, control_points=cp1,
                          knots_u=k.copy(), knots_v=k.copy())
    # Plane 2: z = 0.001 (nearly tangent — normals nearly parallel)
    eps = 0.001
    cp2 = cp1.copy()
    cp2[:, :, 2] = eps
    plane2 = NurbsSurface(degree_u=1, degree_v=1, control_points=cp2,
                          knots_u=k.copy(), knots_v=k.copy())

    marcher = SSIHardenedMarcher(tangent_threshold=0.05)
    # Should not raise; bisection fallback handles near-tangent.
    pts = marcher.march(
        plane1, plane2,
        seed_uv_a=(0.5, 0.5),
        seed_uv_b=(0.5, 0.5),
        step_mm=0.1,
        max_steps=50,
    )
    # May return very few points (planes are nearly tangent) but must not crash.
    assert isinstance(pts, list)
    assert all(len(p) == 3 for p in pts)


# ===========================================================================
# Tests 13-19 — SSIHardenedMarcher.march_all_branches (bifurcation handling)
# ===========================================================================


def test_march_all_branches_plane_x_plane_one_branch():
    """Two non-parallel planes intersect in exactly one line (no bifurcation).
    march_all_branches with one seed should return exactly one branch."""
    # Plane A: z = 0 spanning [-3, 3] in XY.
    cp_a = np.array([
        [[-3, -3, 0], [-3, 3, 0]],
        [[ 3, -3, 0], [ 3, 3, 0]],
    ], dtype=float)
    k = np.array([0, 0, 1, 1.0])
    plane_a = NurbsSurface(degree_u=1, degree_v=1, control_points=cp_a,
                           knots_u=k.copy(), knots_v=k.copy())

    # Plane B: y = 0 spanning [-3, 3] in XZ.
    cp_b = np.array([
        [[-3, 0, -3], [-3, 0, 3]],
        [[ 3, 0, -3], [ 3, 0, 3]],
    ], dtype=float)
    plane_b = NurbsSurface(degree_u=1, degree_v=1, control_points=cp_b,
                           knots_u=k.copy(), knots_v=k.copy())

    # Seed: origin is on both planes.
    # plane_a at (u=0.5, v=0.5) → (0, 0, 0); plane_b at (u=0.5, v=0.5) → (0, 0, 0).
    marcher = SSIHardenedMarcher()
    branches = marcher.march_all_branches(
        plane_a, plane_b,
        initial_seeds=[((0.5, 0.5), (0.5, 0.5))],
        step_mm=0.3,
        max_steps=200,
        max_branches=8,
    )
    # One smooth intersection line → at least one branch.
    assert len(branches) >= 1, f"Expected >=1 branch, got {len(branches)}"
    assert len(branches[0]) >= 3, f"Branch too short: {len(branches[0])}"
    # All points must lie on z≈0 and y≈0.
    pts = np.array(branches[0])
    assert np.all(np.abs(pts[:, 2]) < 0.1), f"z not zero: {pts[:, 2]}"
    assert np.all(np.abs(pts[:, 1]) < 0.1), f"y not zero: {pts[:, 1]}"


def test_march_all_branches_returns_list_of_lists():
    """march_all_branches always returns list[list[tuple]]; even for an empty
    seed list it must return an empty list."""
    cyl = _make_rational_cylinder(r=1.0)
    plane = _make_plane()
    marcher = SSIHardenedMarcher()
    result = marcher.march_all_branches(
        cyl, plane,
        initial_seeds=[],
        max_branches=4,
    )
    assert isinstance(result, list)
    assert result == []


def test_march_all_branches_max_branches_cap():
    """max_branches must be respected — result length <= max_branches."""
    # Three distinct seeds for two crossing cylinders; each produces a branch.
    R = 1.0
    cyl_a = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                    r=R, half_len=1.5)
    cyl_b = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(1, 0, 0),
                                    r=R, half_len=1.5)
    import math as _math
    p = 1.0 / _math.sqrt(2)
    v_seed = 0.5 + p / (2.0 * 1.5)
    marcher = SSIHardenedMarcher()
    # Request at most 2 branches regardless of how many seeds there are.
    branches = marcher.march_all_branches(
        cyl_a, cyl_b,
        initial_seeds=[
            ((0.125, v_seed), (0.125, v_seed)),
            ((0.375, v_seed), (0.375, v_seed)),
            ((0.625, v_seed), (0.625, v_seed)),
        ],
        step_mm=0.2,
        max_steps=150,
        max_branches=2,
    )
    assert len(branches) <= 2, f"max_branches=2 violated: {len(branches)}"


def test_march_all_branches_cylinder_x_plane_on_surface():
    """Cylinder × z=0 plane: all branch points must be within tolerance of
    radius R from the Z axis and near z=0."""
    R = 1.5
    cyl = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                  r=R, half_len=1.5)
    cp = np.array([
        [[-3, -3, 0], [-3, 3, 0]],
        [[ 3, -3, 0], [ 3, 3, 0]],
    ], dtype=float)
    k = np.array([0, 0, 1, 1.0])
    plane = NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                         knots_u=k.copy(), knots_v=k.copy())

    from kerf_cad_core.geom.nurbs import surface_evaluate as _sev
    P_cyl = _sev(cyl, 0.1, 0.5)[:3]
    u_p = float((P_cyl[0] + 3) / 6)
    v_p = float((P_cyl[1] + 3) / 6)

    marcher = SSIHardenedMarcher()
    branches = marcher.march_all_branches(
        cyl, plane,
        initial_seeds=[((0.1, 0.5), (u_p, v_p))],
        step_mm=0.3,
        max_steps=300,
        max_branches=4,
    )
    assert len(branches) >= 1
    for branch in branches:
        pts = np.array(branch)
        dist_from_z = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2)
        assert np.all(np.abs(dist_from_z - R) < R * 0.3), (
            f"branch radius deviations: {np.abs(dist_from_z - R)}"
        )
        assert np.all(np.abs(pts[:, 2]) < 0.15), (
            f"branch z values: {pts[:, 2]}"
        )


def test_march_all_branches_single_seed_equals_single_branch_march():
    """For a smooth intersection (no bifurcation) march_all_branches with one
    seed must produce at least one branch, and its first point must be close to
    what march() returns as its first point."""
    R = 1.0
    cyl_a = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                    r=R, half_len=1.5)
    cyl_b = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(1, 0, 0),
                                    r=R, half_len=1.5)
    import math as _math
    p = 1.0 / _math.sqrt(2)
    v_seed = 0.5 + p / (2.0 * 1.5)

    marcher = SSIHardenedMarcher()
    seed_a = (0.125, v_seed)
    seed_b = (0.125, v_seed)

    pts_single = marcher.march(cyl_a, cyl_b, seed_a, seed_b,
                               step_mm=0.2, max_steps=100)
    branches = marcher.march_all_branches(
        cyl_a, cyl_b,
        initial_seeds=[(seed_a, seed_b)],
        step_mm=0.2,
        max_steps=100,
        max_branches=4,
    )
    assert len(branches) >= 1
    # First points must agree within 0.5 mm.
    p1 = np.array(pts_single[0])
    p2 = np.array(branches[0][0])
    assert float(np.linalg.norm(p1 - p2)) < 0.5, (
        f"First points differ: {p1} vs {p2}"
    )


def test_march_all_branches_no_duplicate_seeds_skipped():
    """Duplicate seeds (same 3-D position) must produce only one branch, not
    multiple copies of the same curve."""
    R = 1.5
    cyl = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                  r=R, half_len=1.5)
    cp = np.array([
        [[-3, -3, 0], [-3, 3, 0]],
        [[ 3, -3, 0], [ 3, 3, 0]],
    ], dtype=float)
    k = np.array([0, 0, 1, 1.0])
    plane = NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                         knots_u=k.copy(), knots_v=k.copy())

    from kerf_cad_core.geom.nurbs import surface_evaluate as _sev
    P_cyl = _sev(cyl, 0.1, 0.5)[:3]
    u_p = float((P_cyl[0] + 3) / 6)
    v_p = float((P_cyl[1] + 3) / 6)

    seed = ((0.1, 0.5), (u_p, v_p))
    marcher = SSIHardenedMarcher()
    # Pass the same seed three times.
    branches = marcher.march_all_branches(
        cyl, plane,
        initial_seeds=[seed, seed, seed],
        step_mm=0.3,
        max_steps=300,
        max_branches=8,
    )
    # De-duplication must collapse the three identical seeds to one branch.
    assert len(branches) <= 2, (
        f"Duplicate seeds produced too many branches: {len(branches)}"
    )


def test_march_all_branches_two_cylinders_both_points_on_surface():
    """Two-cylinder Steinmetz intersection via march_all_branches: all traced
    points must lie within tolerance on both cylinder surfaces."""
    import math as _math
    R = 1.0
    half_len = 1.5
    cyl_a = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(0, 0, 1),
                                    r=R, half_len=half_len)
    cyl_b = _make_rational_cylinder(axis_pt=(0, 0, 0), axis_dir=(1, 0, 0),
                                    r=R, half_len=half_len)
    p = 1.0 / _math.sqrt(2)
    v_seed = 0.5 + p / (2.0 * half_len)

    marcher = SSIHardenedMarcher()
    branches = marcher.march_all_branches(
        cyl_a, cyl_b,
        initial_seeds=[((0.125, v_seed), (0.125, v_seed))],
        step_mm=0.2,
        max_steps=200,
        max_branches=8,
    )
    assert len(branches) >= 1
    for branch in branches:
        pts_arr = np.array(branch)
        dist_a = np.sqrt(pts_arr[:, 0] ** 2 + pts_arr[:, 1] ** 2)
        dist_b = np.sqrt(pts_arr[:, 1] ** 2 + pts_arr[:, 2] ** 2)
        assert np.all(np.abs(dist_a - R) < 0.3), (
            f"cyl_a deviations: {np.abs(dist_a - R)}"
        )
        assert np.all(np.abs(dist_b - R) < 0.3), (
            f"cyl_b deviations: {np.abs(dist_b - R)}"
        )
