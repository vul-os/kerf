"""GK-P49 — characteristic curve extraction on NURBS surfaces.

Four analytic oracles
----------------------
1. **Sphere proxy (paraboloid)**
   A paraboloid z = c(x²+y²) approximates a sphere locally.  At the apex
   all points are umbilic (κ₁ = κ₂ = 1/R), so there should be no distinct
   ridges; the umbilic detector should fire.

2. **Cylinder**
   A degree-2 cylindrical surface: κ₁ = 1/R along the axis direction,
   κ₂ = 0 in the circumferential direction.  K = 0 everywhere → the
   entire surface is parabolic.  extract_characteristic_curves must return
   at least one parabolic curve (or a dense covering of parabolic lines).

3. **Saddle (hyperbolic paraboloid)**
   z = a·x² - b·y²  with a, b > 0: K < 0 everywhere (hyperbolic), so
   there are no parabolic lines.  The centre (u=0.5, v=0.5) is an umbilic
   candidate when a = b (equal-magnitude principal curvatures of opposite
   sign → κ₁ = -κ₂, so |κ₁| = |κ₂| but signs differ — this is NOT a true
   umbilic.  For a true umbilic we need κ₁ = κ₂; on a pure saddle with
   a = b we have κ₁ = 2a > 0, κ₂ = -2a < 0 → not umbilic.

   Oracle: K < 0 everywhere → no parabolic lines.

4. **Torus**
   The torus has K = 0 on the inner and outer equator circles.  These are
   two closed parabolic lines.  We verify:
   * At least 2 distinct parabolic curves are found.
   * Some parabolic points lie close to the known inner / outer equators.

All test surfaces are constructed as pure-Python NurbsSurface objects using
degree-2 polynomial patches, no OCCT dependency.

References
----------
do Carmo §3.3–3.4; Pottmann & Wallner §11.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.characteristic_curves import (
    CharacteristicCurves,
    Curve2D,
    extract_characteristic_curves,
    trace_curve_from_seed,
    _curvature_data,
    _ridge_field,
    _valley_field,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts: list = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def make_paraboloid(R: float = 1.0, half_extent: float = 0.3,
                    nu: int = 7, nv: int = 7) -> NurbsSurface:
    """Degree-2 paraboloid z = c(x²+y²), c = 1/(2R).

    At the apex: κ₁ = κ₂ = 1/R  (all-umbilic, locally spherical).
    K = 1/R² > 0 everywhere (elliptic).
    No parabolic lines.
    """
    c = 1.0 / (2.0 * R)
    deg = 2
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i / (nu - 1) - 0.5) * 2.0 * half_extent
        for j in range(nv):
            y = (j / (nv - 1) - 0.5) * 2.0 * half_extent
            cp[i, j] = [x, y, c * (x * x + y * y)]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_cylinder(R: float = 1.0, height: float = 2.0,
                  nu: int = 9, nv: int = 5) -> NurbsSurface:
    """Degree-2 cylindrical surface sampled over half the circumference.

    Parametric form: x = R·cos(θ), y = R·sin(θ), z = h
    for θ ∈ [0, π], h ∈ [0, height].

    κ₁ = 0 (along the axis), κ₂ = 1/R (circumferential).
    K = κ₁·κ₂ = 0 → the entire surface is parabolic.
    """
    deg = 2
    # Sample θ uniformly, z uniformly
    thetas = np.linspace(0.0, math.pi, nu)
    zs = np.linspace(0.0, height, nv)
    cp = np.zeros((nu, nv, 3))
    for i, theta in enumerate(thetas):
        for j, z in enumerate(zs):
            cp[i, j] = [R * math.cos(theta), R * math.sin(theta), z]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_saddle(a: float = 1.0, b: float = 1.0,
                half_extent: float = 0.4,
                nu: int = 9, nv: int = 9) -> NurbsSurface:
    """Degree-2 hyperbolic paraboloid z = a·x² - b·y².

    K = -4·a·b·(1 + ...) / ...  → K < 0 everywhere (hyperbolic).
    No parabolic lines.
    """
    deg = 2
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = (i / (nu - 1) - 0.5) * 2.0 * half_extent
        for j in range(nv):
            y = (j / (nv - 1) - 0.5) * 2.0 * half_extent
            cp[i, j] = [x, y, a * x * x - b * y * y]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_torus(R: float = 3.0, r: float = 1.0,
               nu: int = 13, nv: int = 9) -> NurbsSurface:
    """Degree-2 torus patch sampled over a full (u × v) ∈ [0,2π] × [0,2π] grid.

    Parametric form:
        x = (R + r·cos(φ))·cos(θ)
        y = (R + r·cos(φ))·sin(θ)
        z =  r·sin(φ)

    Gaussian curvature:
        K = cos(φ) / (r·(R + r·cos(φ)))

    K = 0 when cos(φ) = 0, i.e. φ = π/2 (inner equator, z = r) and
    φ = 3π/2 (outer equator, z = -r).  These are the two closed parabolic
    lines on the torus.
    """
    deg = 2
    thetas = np.linspace(0.0, 2.0 * math.pi, nu)
    phis   = np.linspace(0.0, 2.0 * math.pi, nv)
    cp = np.zeros((nu, nv, 3))
    for i, theta in enumerate(thetas):
        for j, phi in enumerate(phis):
            x = (R + r * math.cos(phi)) * math.cos(theta)
            y = (R + r * math.cos(phi)) * math.sin(theta)
            z = r * math.sin(phi)
            cp[i, j] = [x, y, z]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


# ---------------------------------------------------------------------------
# Oracle 1: Sphere proxy (paraboloid) — umbilic + no parabolic
# ---------------------------------------------------------------------------

class TestSphereOracle:
    """Paraboloid ≈ sphere at apex.

    Expected:
      - K > 0 everywhere (elliptic, no parabolic lines).
      - At the apex κ₁ ≈ κ₂ → umbilic detector fires.
      - No ridge curves (constant curvature paraboloid lacks κ₁ gradient).
    """

    @pytest.fixture(scope="class")
    def surface(self):
        return make_paraboloid(R=1.0, half_extent=0.15, nu=7, nv=7)

    @pytest.fixture(scope="class")
    def result(self, surface):
        return extract_characteristic_curves(surface, n_samples_u=15, n_samples_v=15)

    def test_ok(self, result):
        assert result.ok is True, f"extraction failed: {result.reason}"

    def test_returns_CharacteristicCurves(self, result):
        assert isinstance(result, CharacteristicCurves)

    def test_no_parabolic_lines_on_sphere_proxy(self, result):
        """K > 0 on paraboloid apex region → no parabolic lines."""
        assert len(result.parabolic) == 0, (
            f"Expected 0 parabolic curves on paraboloid, got {len(result.parabolic)}"
        )

    def test_umbilic_point_detected_at_apex(self, result, surface):
        """The paraboloid apex is (approximately) umbilic: κ₁ = κ₂ = 1/R."""
        assert len(result.umbilic_points) >= 1, (
            "Expected at least 1 umbilic point at apex of paraboloid"
        )
        # Verify the umbilic lies near the apex (centre of parameter domain)
        u_mid = 0.5
        v_mid = 0.5
        closest_dist = min(
            abs(u - u_mid) + abs(v - v_mid)
            for u, v in result.umbilic_points
        )
        assert closest_dist < 0.3, (
            f"Umbilic point not near apex: min dist={closest_dist:.4f}"
        )

    def test_curvature_data_at_apex_is_umbilic(self, surface):
        """Direct check: κ₁ ≈ κ₂ at parameter midpoint (apex of paraboloid)."""
        cd = _curvature_data(surface, 0.5, 0.5)
        assert cd is not None
        k1, k2 = cd["k1"], cd["k2"]
        # For paraboloid z = c(x²+y²) with c = 1/(2R) at apex:
        # κ₁ ≈ κ₂ ≈ 1/R = 1.0
        diff = abs(k1 - k2) / (abs(k1) + abs(k2) + 1e-12)
        assert diff < 0.02, (
            f"κ₁={k1:.4f}, κ₂={k2:.4f}, relative diff={diff:.4f} — not umbilic at apex"
        )


# ---------------------------------------------------------------------------
# Oracle 2: Cylinder — K = 0 everywhere → parabolic covering
# ---------------------------------------------------------------------------

class TestCylinderOracle:
    """Cylinder: K = κ₁·κ₂ = 0 everywhere (one principal curvature is zero).

    Expected: parabolic lines cover the entire surface (dense set of K=0 pts).
    extract_characteristic_curves must return at least one parabolic curve.
    """

    @pytest.fixture(scope="class")
    def surface(self):
        return make_cylinder(R=1.0, height=2.0, nu=9, nv=5)

    @pytest.fixture(scope="class")
    def result(self, surface):
        return extract_characteristic_curves(surface, n_samples_u=15, n_samples_v=12)

    def test_ok(self, result):
        assert result.ok is True, f"extraction failed: {result.reason}"

    def test_gaussian_curvature_near_zero_on_cylinder(self, surface):
        """Direct check: K ≈ 0 everywhere on the cylinder."""
        from kerf_cad_core.geom.characteristic_curves import _curvature_data
        K_vals = []
        for u in np.linspace(0.1, 0.9, 8):
            for v in np.linspace(0.1, 0.9, 8):
                cd = _curvature_data(surface, u, v)
                if cd is not None:
                    K_vals.append(cd["K"])

        assert len(K_vals) > 10, "Too few valid curvature samples on cylinder"
        K_arr = np.array(K_vals)
        # Gaussian curvature of a cylinder is exactly 0
        # (tolerance allows for NURBS polynomial approximation error)
        assert np.max(np.abs(K_arr)) < 0.1, (
            f"K not near 0 on cylinder: max|K|={np.max(np.abs(K_arr)):.4f}"
        )

    def test_parabolic_lines_cover_cylinder(self, result):
        """Cylinder is everywhere parabolic → at least 1 parabolic curve returned."""
        assert len(result.parabolic) >= 1, (
            f"Expected ≥1 parabolic curves on cylinder, got {len(result.parabolic)}"
        )

    def test_parabolic_curves_have_sufficient_points(self, result):
        """Each parabolic curve should have at least 2 (u,v) points."""
        for i, curve in enumerate(result.parabolic):
            assert len(curve) >= 2, (
                f"Parabolic curve {i} has only {len(curve)} point(s)"
            )


# ---------------------------------------------------------------------------
# Oracle 3: Saddle (hyperbolic paraboloid) — K < 0 everywhere, no parabolic
# ---------------------------------------------------------------------------

class TestSaddleOracle:
    """Hyperbolic paraboloid z = x² - y²: K < 0 everywhere.

    Expected:
      - No parabolic lines (K never crosses 0).
      - K < 0 is verified analytically.
    """

    @pytest.fixture(scope="class")
    def surface(self):
        return make_saddle(a=1.0, b=1.0, half_extent=0.3, nu=9, nv=9)

    @pytest.fixture(scope="class")
    def result(self, surface):
        return extract_characteristic_curves(surface, n_samples_u=15, n_samples_v=15)

    def test_ok(self, result):
        assert result.ok is True, f"extraction failed: {result.reason}"

    def test_gaussian_curvature_negative_on_saddle(self, surface):
        """Direct check: K < 0 everywhere on the saddle."""
        K_vals = []
        for u in np.linspace(0.1, 0.9, 8):
            for v in np.linspace(0.1, 0.9, 8):
                cd = _curvature_data(surface, u, v)
                if cd is not None:
                    K_vals.append(cd["K"])

        assert len(K_vals) > 10, "Too few valid curvature samples on saddle"
        K_arr = np.array(K_vals)
        # Gaussian curvature of z = x² - y² is negative
        # at all non-degenerate points
        assert np.all(K_arr < 0.01), (
            f"K not negative everywhere on saddle: max K={np.max(K_arr):.4f}"
        )

    def test_no_parabolic_lines_on_saddle(self, result):
        """K < 0 throughout → no parabolic line (K = 0 contour)."""
        assert len(result.parabolic) == 0, (
            f"Expected 0 parabolic curves on saddle, got {len(result.parabolic)}"
        )

    def test_saddle_has_ridges_or_valleys(self, result):
        """Saddle has κ₁/κ₂ gradients → at least one ridge or valley curve."""
        total = len(result.ridges) + len(result.valleys)
        assert total >= 1, (
            f"Expected ≥1 ridge/valley curves on saddle, got {total}"
        )


# ---------------------------------------------------------------------------
# Oracle 4: Torus — two closed parabolic lines (inner + outer equator)
# ---------------------------------------------------------------------------

class TestTorusOracle:
    """Torus K = cos(φ) / (r·(R + r·cos(φ))).

    K = 0 at φ = π/2 (inner equator z = r) and φ = 3π/2 (outer equator z = -r).
    These are two distinct closed parabolic curves.
    """

    @pytest.fixture(scope="class")
    def surface(self):
        return make_torus(R=3.0, r=1.0, nu=13, nv=9)

    @pytest.fixture(scope="class")
    def result(self, surface):
        return extract_characteristic_curves(surface, n_samples_u=20, n_samples_v=18)

    def test_ok(self, result):
        assert result.ok is True, f"extraction failed: {result.reason}"

    def test_torus_gaussian_curvature_sign_varies(self, surface):
        """Torus has both K > 0 (outer half) and K < 0 (inner half)."""
        K_vals = []
        for u in np.linspace(0.05, 0.95, 12):
            for v in np.linspace(0.05, 0.95, 12):
                cd = _curvature_data(surface, u, v)
                if cd is not None:
                    K_vals.append(cd["K"])

        assert len(K_vals) > 20
        K_arr = np.array(K_vals)
        assert np.any(K_arr > 0.01), "Torus should have K > 0 on outer half"
        assert np.any(K_arr < -0.01), "Torus should have K < 0 on inner half"

    def test_torus_has_at_least_two_parabolic_lines(self, result):
        """The torus has exactly 2 closed parabolic lines (inner + outer equators)."""
        assert len(result.parabolic) >= 2, (
            f"Expected ≥2 parabolic curves on torus, got {len(result.parabolic)}"
        )

    def test_parabolic_lines_have_multiple_points(self, result):
        """Each parabolic curve on the torus should be a curve, not a single point."""
        for i, curve in enumerate(result.parabolic):
            assert len(curve) >= 3, (
                f"Torus parabolic curve {i} has only {len(curve)} point(s)"
            )

    def test_parabolic_lines_span_full_u_range(self, result):
        """Torus parabolic lines should span the full u (azimuthal) range."""
        # At least one parabolic curve should have u values spread across [0,1]
        # (it wraps around the torus in the θ direction)
        found_span = False
        for curve in result.parabolic:
            u_vals = [p[0] for p in curve]
            if max(u_vals) - min(u_vals) > 0.5:
                found_span = True
                break
        assert found_span, (
            "No parabolic curve spans the full azimuthal range of the torus"
        )


# ---------------------------------------------------------------------------
# Return type contract
# ---------------------------------------------------------------------------

class TestReturnTypeContract:
    """Verify the return type and structure of CharacteristicCurves."""

    @pytest.fixture(scope="class")
    def result(self):
        surf = make_saddle(nu=7, nv=7)
        return extract_characteristic_curves(surf, n_samples_u=10, n_samples_v=10)

    def test_result_is_CharacteristicCurves(self, result):
        assert isinstance(result, CharacteristicCurves)

    def test_ok_is_bool(self, result):
        assert isinstance(result.ok, bool)

    def test_reason_is_str(self, result):
        assert isinstance(result.reason, str)

    def test_ridges_is_list(self, result):
        assert isinstance(result.ridges, list)

    def test_valleys_is_list(self, result):
        assert isinstance(result.valleys, list)

    def test_parabolic_is_list(self, result):
        assert isinstance(result.parabolic, list)

    def test_umbilic_points_is_list(self, result):
        assert isinstance(result.umbilic_points, list)

    def test_curves_contain_tuples(self, result):
        for curve in result.ridges + result.valleys + result.parabolic:
            assert isinstance(curve, list)
            for pt in curve:
                assert len(pt) == 2

    def test_bad_input_returns_ok_false(self):
        bad = extract_characteristic_curves("not_a_surface")
        assert bad.ok is False
        assert "NurbsSurface" in bad.reason or bad.reason != ""


# ---------------------------------------------------------------------------
# trace_curve_from_seed smoke test
# ---------------------------------------------------------------------------

class TestTraceCurveFromSeed:
    """Smoke tests for the generic RK4 tracer."""

    def test_returns_list_of_tuples(self):
        surf = make_saddle(nu=7, nv=7)
        curve = trace_curve_from_seed(
            surf, (0.5, 0.5), _ridge_field, max_steps=20, step_size=0.05
        )
        assert isinstance(curve, list)
        assert len(curve) >= 1
        for pt in curve:
            assert len(pt) == 2

    def test_curve_stays_in_domain(self):
        surf = make_paraboloid(nu=7, nv=7)
        curve = trace_curve_from_seed(
            surf, (0.5, 0.5), _valley_field, max_steps=50, step_size=0.05
        )
        for u, v in curve:
            assert 0.0 <= u <= 1.0 + 1e-6
            assert 0.0 <= v <= 1.0 + 1e-6

    def test_short_trace_on_plane_valley(self):
        """Flat plane has zero principal curvatures; tracer should still return pts."""
        from kerf_cad_core.geom.nurbs import NurbsSurface
        deg = 2
        nu_p, nv_p = 5, 5
        cp = np.zeros((nu_p, nv_p, 3))
        for i in range(nu_p):
            for j in range(nv_p):
                cp[i, j] = [i / (nu_p - 1), j / (nv_p - 1), 0.0]
        plane = NurbsSurface(
            degree_u=deg, degree_v=deg,
            control_points=cp,
            knots_u=_make_knots(nu_p, deg),
            knots_v=_make_knots(nv_p, deg),
        )
        curve = trace_curve_from_seed(
            plane, (0.5, 0.5), _valley_field, max_steps=10, step_size=0.05
        )
        assert isinstance(curve, list)
