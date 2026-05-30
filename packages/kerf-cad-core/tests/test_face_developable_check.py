"""Hermetic tests for face_developable_check.py -- BREP-FACE-DEVELOPABLE-CHECK.

5 oracle-validated surface types:
  - Cylinder:  K=0 everywhere        → developable=True
  - Sphere:    K=1/R² > 0            → developable=False
  - Cone:      K=0 along rulings     → developable=True
  - Torus:     K varies in sign      → developable=False
  - Plane:     K=0 everywhere        → developable=True

Theory: do Carmo §3.6; Pottmann-Wallner §4.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.face_developable_check import (
    DevelopabilityReport,
    check_face_developable,
)
from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Helpers: NURBS surface constructors (adapted from test_nurbs_normal_curvature)
# ---------------------------------------------------------------------------

def _make_cylinder_nurbs(R: float = 1.0, h: float = 2.0) -> NurbsSurface:
    """Exact rational NURBS cylinder — K=0 everywhere."""
    s = math.sqrt(2.0) / 2.0
    circle_cps = R * np.array([
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
        [-1.0, 1.0],
        [-1.0, 0.0],
        [-1.0, -1.0],
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
    ])
    n_circle = circle_cps.shape[0]  # 9
    cps = np.zeros((n_circle, 2, 3))
    for i in range(n_circle):
        cps[i, 0] = [circle_cps[i, 0], circle_cps[i, 1], 0.0]
        cps[i, 1] = [circle_cps[i, 0], circle_cps[i, 1], h]

    w_circle = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    weights = np.column_stack([w_circle, w_circle])  # (9, 2)
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=1,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_sphere_nurbs(R: float = 1.0) -> NurbsSurface:
    """Rational biquadratic sphere NURBS — K=1/R² everywhere (umbilic)."""
    s = math.sqrt(2.0) / 2.0
    lat_cps_xz = np.array([
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
    ])
    lat_weights = np.array([1.0, s, 1.0, s, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])
    circle_xy = np.array([
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
        [-1.0, 1.0],
        [-1.0, 0.0],
        [-1.0, -1.0],
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
    ])
    circle_weights = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    n_lon, n_lat = 9, 5
    cps = np.zeros((n_lon, n_lat, 3))
    weights = np.zeros((n_lon, n_lat))
    for i_lat in range(n_lat):
        r = lat_cps_xz[i_lat, 0]
        z = lat_cps_xz[i_lat, 1]
        w_lat = lat_weights[i_lat]
        for j_lon in range(n_lon):
            x = r * circle_xy[j_lon, 0]
            y = r * circle_xy[j_lon, 1]
            w_lon = circle_weights[j_lon]
            cps[j_lon, i_lat] = [R * x, R * y, R * z]
            weights[j_lon, i_lat] = w_lon * w_lat
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_flat_nurbs(nu: int = 4, nv: int = 4) -> NurbsSurface:
    """Flat planar NURBS in Z=0 — K=0 everywhere."""
    d = 3
    def _ku(n):
        interior = (n + d + 1) - 2 * (d + 1)
        k = [0.0] * (d + 1)
        for i in range(1, interior + 1):
            k.append(float(i) / float(interior + 1))
        k += [1.0] * (d + 1)
        return np.array(k, dtype=float)

    cp = np.zeros((nu, nv, 3), dtype=float)
    for i, u in enumerate(np.linspace(0.0, 1.0, nu)):
        for j, v in enumerate(np.linspace(0.0, 1.0, nv)):
            cp[i, j] = [u, v, 0.0]
    return NurbsSurface(degree_u=d, degree_v=d,
                        control_points=cp, knots_u=_ku(nu), knots_v=_ku(nv))


def _make_cone_nurbs(R_base: float = 1.0, height: float = 2.0) -> NurbsSurface:
    """Rational NURBS cone (apex at z=height, base circle at z=0).

    Built as a degenerate cylinder where the top circle contracts to the apex.
    K=0 everywhere except at the apex (degenerate point, skipped by checker).
    """
    s = math.sqrt(2.0) / 2.0
    circle_cps = np.array([
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
        [-1.0, 1.0],
        [-1.0, 0.0],
        [-1.0, -1.0],
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
    ])
    n_circle = circle_cps.shape[0]  # 9
    cps = np.zeros((n_circle, 2, 3))
    for i in range(n_circle):
        # bottom: base circle at z=0 with radius R_base
        cps[i, 0] = [R_base * circle_cps[i, 0], R_base * circle_cps[i, 1], 0.0]
        # top: apex (degenerate circle collapsed to point) at z=height
        cps[i, 1] = [0.0, 0.0, height]

    w_circle = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    # apex row also uses the same weights (harmless for degenerate point)
    weights = np.column_stack([w_circle, w_circle])  # (9, 2)
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=1,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


class _FaceLike:
    """Minimal Face stub — wraps a surface object for check_face_developable."""
    def __init__(self, surface):
        self.surface = surface


# ---------------------------------------------------------------------------
# Tests: Cylinder (developable)
# ---------------------------------------------------------------------------

class TestCylinderDevelopable:
    """Cylinder — K=0 everywhere → is_developable=True."""

    def setup_method(self):
        self.srf = _make_cylinder_nurbs(R=1.0, h=2.0)
        self.face = _FaceLike(self.srf)

    def test_is_developable_true(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.is_developable is True

    def test_max_K_near_zero(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.max_abs_K < 1e-6, f"max|K|={r.max_abs_K} expected <1e-6 for cylinder"

    def test_mean_K_near_zero(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.mean_abs_K < 1e-6

    def test_samples_valid_positive(self):
        r = check_face_developable(self.face, samples=5)
        assert r.samples_valid > 0

    def test_report_type(self):
        r = check_face_developable(self.face)
        assert isinstance(r, DevelopabilityReport)

    def test_tolerance_stored(self):
        r = check_face_developable(self.face, tolerance=0.01)
        assert r.tolerance == pytest.approx(0.01)

    def test_ruled_direction_reported(self):
        # Cylinder: κ_2 (height direction) = 0 → should identify a ruling direction
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.ruled_direction_if_any in ("kappa_1", "kappa_2")


# ---------------------------------------------------------------------------
# Tests: Sphere (non-developable)
# ---------------------------------------------------------------------------

class TestSphereDevelopable:
    """Unit sphere — K=1/R² > 0 → is_developable=False."""

    def setup_method(self):
        self.R = 2.0
        self.srf = _make_sphere_nurbs(R=self.R)
        self.face = _FaceLike(self.srf)

    def test_is_developable_false(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.is_developable is False

    def test_max_K_positive(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        expected_K = 1.0 / (self.R ** 2)
        # max|K| should be close to 1/R² (sphere is umbilic)
        assert r.max_abs_K > expected_K * 0.5, (
            f"max|K|={r.max_abs_K} expected ~{expected_K:.4f} for R={self.R} sphere"
        )

    def test_not_ruled(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        # Sphere is umbilic (κ_1=κ_2≠0), neither principal curvature is zero
        assert r.ruled_direction_if_any is None

    def test_samples_valid_positive(self):
        r = check_face_developable(self.face, samples=5)
        assert r.samples_valid > 0


# ---------------------------------------------------------------------------
# Tests: Cone (developable)
# ---------------------------------------------------------------------------

class TestConeDevelopable:
    """Cone — K=0 along ruling lines → is_developable=True.

    The apex row of a cone is degenerate (|S_u × S_v|=0); those samples
    are skipped. The non-degenerate rulings should all yield K=0.
    """

    def setup_method(self):
        self.srf = _make_cone_nurbs(R_base=1.0, height=2.0)
        self.face = _FaceLike(self.srf)

    def test_is_developable_true(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.is_developable is True, (
            f"Cone should be developable; max|K|={r.max_abs_K}"
        )

    def test_max_K_near_zero(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=8)
        assert r.max_abs_K < 1e-3, f"Cone max|K|={r.max_abs_K} expected <1e-3"


# ---------------------------------------------------------------------------
# Tests: Torus (non-developable)
# ---------------------------------------------------------------------------

class TestTorusDevelopable:
    """Torus — K varies in sign → is_developable=False."""

    def setup_method(self):
        from kerf_cad_core.geom.brep import TorusSurface
        # Torus: R_major=3, r_minor=1 — K = cos(v)/(r*(R+r*cos(v)))
        # K > 0 on outer belt, K < 0 on inner belt → max|K| > 0
        torus = TorusSurface(
            center=np.array([0.0, 0.0, 0.0]),
            axis=np.array([0.0, 0.0, 1.0]),
            major_radius=3.0,
            minor_radius=1.0,
        )
        # Give it knot-vector attributes so UV domain detection works
        torus.knots_u = np.array([0.0, 0.0, 2.0 * math.pi, 2.0 * math.pi])
        torus.knots_v = np.array([0.0, 0.0, 2.0 * math.pi, 2.0 * math.pi])
        self.face = _FaceLike(torus)

    def test_is_developable_false(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=10)
        # max|K| > 0 for a torus (varies, never uniformly zero)
        assert r.is_developable is False, (
            f"Torus should NOT be developable; max|K|={r.max_abs_K}"
        )

    def test_max_K_positive(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=10)
        assert r.max_abs_K > 1e-3

    def test_samples_valid_positive(self):
        r = check_face_developable(self.face, tolerance=1e-3, samples=10)
        assert r.samples_valid > 0


# ---------------------------------------------------------------------------
# Tests: Plane (developable)
# ---------------------------------------------------------------------------

class TestPlaneDevelopable:
    """Flat plane — K=0 everywhere → is_developable=True."""

    def setup_method(self):
        self.srf = _make_flat_nurbs()
        self.face = _FaceLike(self.srf)

    def test_is_developable_true(self):
        r = check_face_developable(self.face, tolerance=1e-6, samples=8)
        assert r.is_developable is True

    def test_max_K_nearly_zero(self):
        r = check_face_developable(self.face, tolerance=1e-6, samples=8)
        assert r.max_abs_K < 1e-8

    def test_both_principal_curvatures_zero(self):
        # For a flat plane both κ_1=κ_2=0, ruling direction is reported
        r = check_face_developable(self.face, tolerance=1e-6, samples=8)
        assert r.ruled_direction_if_any in ("kappa_1", "kappa_2")


# ---------------------------------------------------------------------------
# Tests: Report structure & honest caveat
# ---------------------------------------------------------------------------

class TestReportStructure:
    """Validate report fields are well-formed regardless of surface type."""

    def setup_method(self):
        self.srf = _make_flat_nurbs()
        self.face = _FaceLike(self.srf)

    def test_honest_caveat_present(self):
        r = check_face_developable(self.face)
        assert r.honest_caveat
        assert "sampling" in r.honest_caveat.lower()

    def test_samples_valid_gte_zero(self):
        r = check_face_developable(self.face, samples=2)
        assert r.samples_valid >= 0

    def test_max_ge_mean(self):
        r = check_face_developable(self.face, samples=5)
        assert r.max_abs_K >= r.mean_abs_K - 1e-15

    def test_default_tolerance_stored(self):
        r = check_face_developable(self.face)
        assert r.tolerance == pytest.approx(1e-3)
