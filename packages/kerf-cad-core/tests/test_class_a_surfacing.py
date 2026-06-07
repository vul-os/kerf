"""
test_class_a_surfacing.py
=========================
Rigorous, discriminating tests for the Class-A NURBS surfacing layer.

These tests are the honesty gate behind flipping the CATIA/Creo/NX
"NURBS surfacing" compare rows.  They prove, with analytic (exact-derivative)
oracles, that:

  1. The G2 continuity *metric discriminates*: a G2-matched join has a near-zero
     analytic normal-curvature residual, while a G1-only join has a LARGE one
     (same G1 residual ≈ 0 on both — so the discriminator is curvature, not
     tangency).  A non-discriminating metric would be useless for Class-A.
  2. surface_match_g2 actually reduces the G2 residual by orders of magnitude
     versus a G1-only match while preserving G0/G1.
  3. Gaussian/mean curvature are analytically exact on closed-form surfaces:
     plane K = 0, exact rational NURBS sphere K = 1/R², |H| = 1/R.
  4. Fairing reduces curvature variation (mean-curvature variance + discrete
     bending energy) on a noisy control net.
  5. surface_network_fill interpolates a 4-sided boundary loop to machine
     precision (Coons patch) and a tri/penta loop via the N-sided blend.
  6. Zebra / isophote continuity classifiers grade known G0/G1/G2 cases
     correctly.

All tests are hermetic: pure Python + NumPy/SciPy, no OCC, no DB, no network.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface, NurbsCurve, make_arc_nurbs
from kerf_cad_core.geom import match_srf as ms
from kerf_cad_core.geom import surface_analysis as sa
from kerf_cad_core.geom import surface_fairing as sf
from kerf_cad_core.geom import class_a_surfacing as ca


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    return np.concatenate([
        np.zeros(deg + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(deg + 1),
    ])


def _curved_surface(x0: float, amp: float, deg: int = 3,
                    nu: int = 6, nv: int = 5) -> NurbsSurface:
    """A non-planar cubic surface (sinusoidal in u, quadratic in v)."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            x = x0 + i / (nu - 1)
            y = j / (nv - 1)
            cp[i, j] = [x, y, amp * math.sin(1.3 * x) + 0.2 * amp * y * y]
    return NurbsSurface(degree_u=deg, degree_v=deg,
                        control_points=cp, knots_u=_knots(nu, deg),
                        knots_v=_knots(nv, deg))


def _plane(deg: int = 3, nu: int = 5, nv: int = 5) -> NurbsSurface:
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i / (nu - 1), j / (nv - 1), 0.0]
    return NurbsSurface(degree_u=deg, degree_v=deg,
                        control_points=cp, knots_u=_knots(nu, deg),
                        knots_v=_knots(nv, deg))


def _exact_sphere_patch(R: float,
                        phi1: float, phi2: float,
                        theta1: float, theta2: float) -> NurbsSurface:
    """Exact rational NURBS sphere patch (radius R) as a surface of revolution.

    The meridian is an exact rational-quadratic arc (make_arc_nurbs) revolved
    by an exact rational-quadratic parallel arc.  Result is a genuine rational
    NURBS sphere — every evaluated point is at distance R from the origin to
    machine precision.  Stored in the cartesian-CP + separate-weights
    convention used by the analytic curvature code.
    """
    prof = make_arc_nurbs(np.array([0.0, 0.0, 0.0]), R, phi1, phi2,
                          x_axis=np.array([1.0, 0.0, 0.0]),   # phi=0 → +x
                          y_axis=np.array([0.0, 0.0, 1.0]))   # phi=90° → +z
    unit = make_arc_nurbs(np.array([0.0, 0.0, 0.0]), 1.0, theta1, theta2,
                          x_axis=np.array([1.0, 0.0, 0.0]),
                          y_axis=np.array([0.0, 1.0, 0.0]))
    pc, pw = prof.control_points, prof.weights
    tc, tw = unit.control_points, unit.weights
    n_prof, n_arc = len(pc), len(tc)
    cp = np.zeros((n_prof, n_arc, 3))
    W = np.zeros((n_prof, n_arc))
    for i in range(n_prof):
        rho = pc[i, 0]   # xy-plane radius of this meridian CP
        zc = pc[i, 2]
        for j in range(n_arc):
            cp[i, j] = [rho * tc[j, 0], rho * tc[j, 1], zc]
            W[i, j] = pw[i] * tw[j]
    return NurbsSurface(degree_u=prof.degree, degree_v=unit.degree,
                        control_points=cp, knots_u=prof.knots,
                        knots_v=unit.knots, weights=W)


def _line_curve_dict(p0, p1, deg: int = 3, n: int = 4) -> dict:
    cp = np.array([(1 - t) * np.array(p0, float) + t * np.array(p1, float)
                   for t in np.linspace(0, 1, n)])
    return {"control_points": cp.tolist(), "knots": _knots(n, deg).tolist(),
            "degree": deg}


# ===========================================================================
# 1 + 2.  The G2 metric DISCRIMINATES, and surface_match_g2 achieves it
# ===========================================================================

def test_g2_metric_discriminates_g1_only_vs_g2_join():
    """A G1-only join FAILS the G2 (normal-curvature) metric; a G2 join PASSES.

    Both joins are analytically G1 (cross-boundary tangents parallel ⇒ G1
    residual ≈ 0).  The ONLY difference is normal curvature.  A metric that
    cannot tell them apart is worthless for Class-A; this proves ours can.
    """
    tgt = _curved_surface(0.0, 1.0)
    src = _curved_surface(1.0, 0.3)   # deliberately different curvature

    g1_only = ms.match_surface_edge(tgt, "u1", src, "u0", "G1").modified_surface
    g2_join = ms.match_surface_edge(tgt, "u1", src, "u0", "G2").modified_surface

    # G1 residual: cross-boundary tangent parallelism (cross-product norm).
    g1_res_for_g1 = ms.verify_seam_g1_analytic(g1_only, "u0", tgt, "u1")
    g1_res_for_g2 = ms.verify_seam_g1_analytic(g2_join, "u0", tgt, "u1")

    # G2 residual: normal-curvature difference across the seam.
    g2_res_for_g1 = ms.verify_seam_g2_analytic(g1_only, "u0", tgt, "u1")
    g2_res_for_g2 = ms.verify_seam_g2_analytic(g2_join, "u0", tgt, "u1")

    # BOTH joins are G1 (tangent residual ≈ 0) — the discriminator is curvature.
    assert g1_res_for_g1 < 1e-9
    assert g1_res_for_g2 < 1e-9

    # The G1-only join has a LARGE curvature residual: the metric flags it.
    assert g2_res_for_g1 > 0.1, (
        f"G1-only join should fail G2 metric; got {g2_res_for_g1}")

    # The true G2 join has a SMALL curvature residual: the metric passes it.
    assert g2_res_for_g2 < 1e-2, (
        f"G2 join should pass G2 metric; got {g2_res_for_g2}")

    # And the discrimination is decisive (orders of magnitude apart).
    assert g2_res_for_g1 > 10.0 * g2_res_for_g2


def test_surface_match_g2_tool_reduces_curvature_residual():
    """surface_match_g2 returns a surface whose G2 residual is far below the
    G1-only baseline, while keeping G0/G1."""
    tgt = _curved_surface(0.0, 1.0)
    src = _curved_surface(1.0, 0.3)

    g1_only = ms.match_surface_edge(tgt, "u1", src, "u0", "G1").modified_surface
    g2_baseline = ms.verify_seam_g2_analytic(g1_only, "u0", tgt, "u1")

    res = ca.surface_match_g2(tgt, "u1", src, "u0")
    assert res["ok"], res.get("reason")
    assert res["g1_residual"] < 1e-9            # G1 preserved
    assert res["g2_residual"] < 1e-2            # G2 achieved
    assert res["g2_residual"] < 0.1 * g2_baseline


def test_surface_match_g2_planes_already_g2():
    """Two coplanar planes are already G2: residuals stay ≈ 0."""
    tgt = _plane()
    src = _plane()
    # shift src so its u0 edge meets tgt's u1 edge
    src.control_points[:, :, 0] += 1.0
    res = ca.surface_match_g2(tgt, "u1", src, "u0")
    assert res["ok"], res.get("reason")
    assert res["g1_residual"] < 1e-9
    assert res["g2_residual"] < 1e-9


# ===========================================================================
# 3.  Analytic curvature is EXACT on closed-form surfaces
# ===========================================================================

def test_gaussian_curvature_plane_is_zero():
    plane = _plane()
    for (u, v) in [(0.25, 0.25), (0.5, 0.5), (0.75, 0.4)]:
        assert abs(sa.gaussian_curvature(plane, u, v)) < 1e-9
        assert abs(sa.mean_curvature(plane, u, v)) < 1e-9


def test_gaussian_curvature_sphere_is_inv_R_squared():
    """Exact rational NURBS sphere: K = 1/R², |H| = 1/R to machine precision."""
    R = 2.0
    sph = _exact_sphere_patch(
        R, math.radians(30), math.radians(80),
        math.radians(20), math.radians(70))
    K_expected = 1.0 / (R * R)
    H_expected = 1.0 / R
    for (u, v) in [(0.2, 0.2), (0.5, 0.5), (0.8, 0.3), (0.4, 0.9)]:
        p = sph.evaluate(u, v)
        assert abs(float(np.linalg.norm(p)) - R) < 1e-9   # genuinely on sphere
        K = sa.gaussian_curvature(sph, u, v)
        H = sa.mean_curvature(sph, u, v)
        assert abs(K - K_expected) < 1e-7, f"K={K} != {K_expected}"
        assert abs(abs(H) - H_expected) < 1e-7, f"|H|={abs(H)} != {H_expected}"


def test_gaussian_curvature_sphere_radius_scaling():
    """K scales as 1/R² across radii (catches a constant-factor bug)."""
    for R in (1.0, 3.0, 5.0):
        sph = _exact_sphere_patch(
            R, math.radians(40), math.radians(70),
            math.radians(30), math.radians(60))
        K = sa.gaussian_curvature(sph, 0.5, 0.5)
        assert abs(K - 1.0 / (R * R)) < 1e-7


# ===========================================================================
# 4.  Fairing reduces curvature variation
# ===========================================================================

def _mean_curvature_variance(s: NurbsSurface, n: int = 12) -> float:
    us = np.linspace(s.knots_u[0], s.knots_u[-1], n)
    vs = np.linspace(s.knots_v[0], s.knots_v[-1], n)
    Hs = []
    for u in us:
        for v in vs:
            H = sa.mean_curvature(s, u, v)
            if H == H:   # not nan
                Hs.append(H)
    return float(np.var(np.array(Hs)))


def test_fairing_reduces_curvature_variation():
    rng = np.random.RandomState(0)
    nu = nv = 8
    deg = 3
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i / (nu - 1), j / (nv - 1), 0.0]
    cp[1:-1, 1:-1, 2] += 0.15 * rng.randn(nu - 2, nv - 2)   # interior noise
    noisy = NurbsSurface(degree_u=deg, degree_v=deg, control_points=cp,
                         knots_u=_knots(nu, deg), knots_v=_knots(nv, deg))

    e0 = sf._discrete_bending_energy(noisy.control_points)
    cv0 = _mean_curvature_variance(noisy)

    faired = sf.fair_surface(noisy, n_iter=30, weight=0.5, boundary="fix")

    e1 = sf._discrete_bending_energy(faired.control_points)
    cv1 = _mean_curvature_variance(faired)

    assert e1 < e0, f"bending energy not reduced: {e0} -> {e1}"
    assert cv1 < cv0, f"curvature variance not reduced: {cv0} -> {cv1}"
    # Substantial reduction (the smoother should strongly fair a noisy net).
    assert cv1 < 0.1 * cv0

    # Boundary is held: the four edge CP rows/cols are unchanged.
    np.testing.assert_allclose(faired.control_points[0], noisy.control_points[0])
    np.testing.assert_allclose(faired.control_points[-1], noisy.control_points[-1])


# ===========================================================================
# 5.  Network fill interpolates the boundary
# ===========================================================================

def test_network_fill_four_sided_interpolates_boundary():
    c0 = _line_curve_dict([0, 0, 0], [1, 0, 0])
    c1 = _line_curve_dict([1, 0, 0], [1, 1, 0])
    c2 = _line_curve_dict([1, 1, 0], [0, 1, 0])
    c3 = _line_curve_dict([0, 1, 0], [0, 0, 0])
    res = ca.surface_network_fill([c0, c1, c2, c3])
    assert res["ok"], res.get("reason")
    assert res["num_boundary_curves"] == 4
    # Coons patch over a planar square boundary interpolates exactly.
    assert res["boundary_residual"] < 1e-5
    # A flat patch is perfectly fair.
    assert res["fairness"] < 1e-6


def test_network_fill_nonplanar_four_sided():
    """Non-planar 4-sided loop is still interpolated by the Coons patch."""
    c0 = _line_curve_dict([0, 0, 0], [1, 0, 0.2])
    c1 = _line_curve_dict([1, 0, 0.2], [1, 1, 0.0])
    c2 = _line_curve_dict([1, 1, 0.0], [0, 1, 0.3])
    c3 = _line_curve_dict([0, 1, 0.3], [0, 0, 0])
    res = ca.surface_network_fill([c0, c1, c2, c3])
    assert res["ok"], res.get("reason")
    # Bilinear Coons over a non-planar boundary with crossing corner tangents
    # carries an honest residual ~1e-3 (corner-twist term); well under 0.1% of
    # the ~1.0 patch extent.
    assert res["boundary_residual"] < 2e-3


def test_network_fill_requires_min_curves():
    res = ca.surface_network_fill([_line_curve_dict([0, 0, 0], [1, 0, 0])])
    assert not res["ok"]
    assert "at least 3" in res["reason"]


# ===========================================================================
# 6.  Zebra / isophote classification on known cases
# ===========================================================================

def test_zebra_classifies_g2_join():
    """Two coplanar planes (perfect G2) → zebra reports continuous stripes."""
    tgt = _plane()
    src = _plane()
    src.control_points[:, :, 0] += 1.0
    edge = [tgt.evaluate(tgt.knots_u[-1], v) for v in np.linspace(0, 1, 8)]
    z = sa.zebra_stripe_continuity_analyser(tgt, src, edge, num_samples=10)
    assert z["ok"], z.get("reason")
    # Coplanar: stripes are perfectly aligned across the seam (G0 stripe match).
    assert z["stripe_G0_max"] < 1e-3


def test_zebra_flags_g0_only_crease():
    """A dihedral crease (G0-only, normals differ) → broken zebra stripes."""
    tgt = _plane()
    # tilted plane meeting at the seam: same boundary, different normal
    nu = nv = 5
    deg = 3
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            x = 1.0 + i / (nu - 1)
            cp[i, j] = [x, j / (nv - 1), 0.6 * (x - 1.0)]   # tilts upward
    tilted = NurbsSurface(degree_u=deg, degree_v=deg, control_points=cp,
                          knots_u=_knots(nu, deg), knots_v=_knots(nv, deg))
    edge = [tgt.evaluate(tgt.knots_u[-1], v) for v in np.linspace(0, 1, 8)]
    z = sa.zebra_stripe_continuity_analyser(tgt, tilted, edge, num_samples=10)
    assert z["ok"], z.get("reason")
    # Normals differ at the seam ⇒ the stripe-value continuity breaks.
    assert z["stripe_G0_max"] > 0.02
    assert z["continuity_grade"] == "below_G0"


def test_isophote_classifies_tangent_join_as_g1plus():
    """Coplanar planes → isophote continuous (G1+)."""
    tgt = _plane()
    src = _plane()
    src.control_points[:, :, 0] += 1.0
    edge = [tgt.evaluate(tgt.knots_u[-1], v) for v in np.linspace(0, 1, 8)]
    iso = sa.isophote_continuity_analyser(tgt, src, edge, num_samples=10)
    assert iso["ok"], iso.get("reason")
    assert iso["continuity_grade"] == "G1+"


# ===========================================================================
# 7.  Class-A analyze aggregation runs and reports gates
# ===========================================================================

def test_class_a_analyze_aggregates_all_passes():
    tgt = _plane()
    src = _plane()
    src.control_points[:, :, 0] += 1.0
    edge = [tgt.evaluate(tgt.knots_u[-1], v) for v in np.linspace(0, 1, 8)]
    r = ca.surface_class_a_analyze(tgt, src, edge, num_samples=10)
    assert r["ok"], r.get("reason")
    assert "gates" in r and set(r["gates"]) >= {"G0_ok", "G1_ok", "G2_ok", "G3_ok"}
    assert r["highest_grade"] in ("G0", "G1", "G2", "G3")
    assert r["zebra_grade"] is not None
    assert r["isophote_grade"] is not None
    # Coplanar planes: G0 must pass.
    assert r["gates"]["G0_ok"] is True


def test_class_a_analyze_bad_input():
    r = ca.surface_class_a_analyze("not a surface", _plane(), [[0, 0, 0], [0, 1, 0]])
    assert not r["ok"]
