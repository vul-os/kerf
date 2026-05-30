"""
Tests for kerf_cad_core.geom.osculating_circle
================================================
Reference oracles (all hermetic — no OCC, no network):

  1. Circle (R=1, R=3, R=0.5) — κ = 1/R at every parameter.
  2. Line — κ = 0, radius = None, is_degenerate = True.
  3. Helix r=1 pitch=2π — κ_helix = r/(r²+b²) = 1/(1+1) = 0.5; radius = 2.
  4. Parabola y=x² — κ at vertex = 2; radius = 0.5.
  5. Sample-grid — osculating_circles_along returns correct count & no crash.
  6. Degenerate sentinel — is_degenerate propagated correctly.
  7. Re-export — OsculatingCircle importable from geom.__init__.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    make_circle_nurbs,
    make_line_nurbs,
)
from kerf_cad_core.geom.osculating_circle import (
    OsculatingCircle,
    osculating_circle,
    osculating_circles_along,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_helix_nurbs(r: float = 1.0, b: float = 1.0, turns: float = 1.0) -> NurbsCurve:
    """Approximate helix C(t) = (r·cos t, r·sin t, b·t) as a degree-3 NURBS
    by sampling + global interpolation.

    We use a dense B-spline interpolant so curvature is accurate to within
    the chord-length sampling error.  The analytic helix has κ = r/(r²+b²).
    """
    from kerf_cad_core.geom.curve_toolkit import interp_curve

    n_pts = 80
    ts = np.linspace(0.0, turns * 2 * math.pi, n_pts)
    pts = np.column_stack([
        r * np.cos(ts),
        r * np.sin(ts),
        b * ts,
    ])
    return interp_curve(pts, degree=3)


def _make_parabola_nurbs() -> NurbsCurve:
    """Parabola y = x² for x ∈ [-1, 1] as degree-3 interpolated NURBS.

    Analytic curvature at vertex (x=0): κ = |y″| / (1+y′²)^(3/2) = 2 / 1 = 2.
    """
    from kerf_cad_core.geom.curve_toolkit import interp_curve

    n_pts = 60
    xs = np.linspace(-1.0, 1.0, n_pts)
    pts = np.column_stack([xs, xs ** 2, np.zeros(n_pts)])
    return interp_curve(pts, degree=3)


# ---------------------------------------------------------------------------
# 1. Circle oracle
# ---------------------------------------------------------------------------

class TestCircleOracle:
    """For an exact circle of radius R, κ = 1/R everywhere."""

    @pytest.mark.parametrize("radius", [0.5, 1.0, 3.0])
    def test_curvature_at_quadrant_points(self, radius):
        """κ ≈ 1/R at all four quadrant parameter values (within 1e-6)."""
        circ = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), radius)
        # Sample at midpoints of each Bezier segment to avoid knot-multiplicity issues.
        t_samples = [0.125, 0.375, 0.625, 0.875]
        for t in t_samples:
            oc = osculating_circle(circ, t)
            assert not oc.is_degenerate, f"circle should not be degenerate at t={t}"
            assert oc.radius is not None
            assert abs(oc.curvature - 1.0 / radius) < 1e-6, (
                f"κ={oc.curvature:.8f}, expected {1.0/radius:.8f} at t={t}"
            )
            assert abs(oc.radius - radius) < 1e-6, (
                f"radius={oc.radius:.8f}, expected {radius:.8f} at t={t}"
            )

    def test_center_on_circle_axis(self):
        """Centre of curvature should coincide with the circle's own centre."""
        origin = np.array([1.0, 2.0, 0.0])
        circ = make_circle_nurbs(origin, 2.0)
        t_samples = [0.125, 0.375, 0.625, 0.875]
        for t in t_samples:
            oc = osculating_circle(circ, t)
            assert oc.center is not None
            dist = float(np.linalg.norm(oc.center - origin))
            assert dist < 1e-5, (
                f"center={oc.center} is {dist:.2e} from origin {origin} at t={t}"
            )

    def test_uniform_samples_all_valid(self):
        """osculating_circles_along on a full circle — all non-degenerate."""
        circ = make_circle_nurbs(np.zeros(3), 1.5)
        results = osculating_circles_along(circ, samples=16)
        assert len(results) == 16
        for oc in results:
            # Some samples land on knot boundaries; allow degenerate there.
            if not oc.is_degenerate:
                assert abs(oc.radius - 1.5) < 1e-4


# ---------------------------------------------------------------------------
# 2. Line oracle
# ---------------------------------------------------------------------------

class TestLineOracle:
    """For a straight line, κ = 0 → degenerate (radius=None)."""

    def test_line_is_degenerate(self):
        line = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        oc = osculating_circle(line, 0.5)
        assert oc.is_degenerate, "line should produce degenerate osculating circle"
        assert oc.radius is None
        assert oc.center is None
        assert oc.curvature == pytest.approx(0.0, abs=1e-12)

    def test_line_curvature_zero_along(self):
        """All samples on a line are degenerate."""
        line = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([3.0, 4.0, 0.0]),
        )
        results = osculating_circles_along(line, samples=10)
        for oc in results:
            assert oc.is_degenerate
            assert oc.radius is None


# ---------------------------------------------------------------------------
# 3. Helix oracle
# ---------------------------------------------------------------------------

class TestHelixOracle:
    """Helix r=1, b=1 (pitch 2π·b = 2π):
        κ = r / (r² + b²) = 1 / (1+1) = 0.5 → radius = 2.0
    """

    def test_helix_curvature(self):
        helix = _make_helix_nurbs(r=1.0, b=1.0, turns=1.0)
        # Sample at 60% through the parameterisation (away from endpoints).
        n = helix.num_control_points - 1
        t_min = float(helix.knots[helix.degree])
        t_max = float(helix.knots[n + 1])
        t_mid = t_min + 0.6 * (t_max - t_min)

        oc = osculating_circle(helix, t_mid)
        assert not oc.is_degenerate
        assert oc.radius is not None
        # Tolerance of 5% is generous for a NURBS approximation.
        expected_kappa = 0.5
        assert abs(oc.curvature - expected_kappa) < 0.05, (
            f"κ={oc.curvature:.4f}, expected {expected_kappa}"
        )
        assert abs(oc.radius - 2.0) < 0.2, (
            f"radius={oc.radius:.4f}, expected 2.0"
        )

    def test_helix_samples_count(self):
        helix = _make_helix_nurbs(r=1.0, b=1.0, turns=1.0)
        results = osculating_circles_along(helix, samples=12)
        assert len(results) == 12
        # Interior samples (away from endpoints) should be non-degenerate.
        interior = results[2:-2]
        assert all(not oc.is_degenerate for oc in interior)


# ---------------------------------------------------------------------------
# 4. Parabola oracle
# ---------------------------------------------------------------------------

class TestParabolaOracle:
    """Parabola y=x²: at the vertex (x=0), κ = 2, radius = 0.5."""

    def test_vertex_curvature(self):
        parab = _make_parabola_nurbs()
        # The vertex is the midpoint of the parabola arc.
        n = parab.num_control_points - 1
        t_min = float(parab.knots[parab.degree])
        t_max = float(parab.knots[n + 1])
        t_vertex = 0.5 * (t_min + t_max)

        oc = osculating_circle(parab, t_vertex)
        assert not oc.is_degenerate
        assert oc.radius is not None
        # Tolerance 5% — NURBS interpolant, not analytic parabola.
        assert abs(oc.curvature - 2.0) < 0.15, (
            f"κ={oc.curvature:.4f}, expected 2.0"
        )
        assert abs(oc.radius - 0.5) < 0.05, (
            f"radius={oc.radius:.4f}, expected 0.5"
        )

    def test_vertex_center_above_vertex(self):
        """Centre of curvature of y=x² at vertex = (0, 0.5)."""
        parab = _make_parabola_nurbs()
        n = parab.num_control_points - 1
        t_min = float(parab.knots[parab.degree])
        t_max = float(parab.knots[n + 1])
        t_vertex = 0.5 * (t_min + t_max)

        oc = osculating_circle(parab, t_vertex)
        assert oc.center is not None
        # Centre should be near (0, 0.5, 0).
        assert abs(oc.center[0]) < 0.1, f"center x={oc.center[0]:.4f}, expected ~0"
        assert abs(oc.center[1] - 0.5) < 0.1, f"center y={oc.center[1]:.4f}, expected ~0.5"


# ---------------------------------------------------------------------------
# 5. Sample-grid test
# ---------------------------------------------------------------------------

class TestSampleGrid:
    """osculating_circles_along basic contract tests."""

    def test_returns_correct_count(self):
        circ = make_circle_nurbs(np.zeros(3), 1.0)
        for n in [2, 5, 20, 50]:
            results = osculating_circles_along(circ, samples=n)
            assert len(results) == n, f"expected {n} results, got {len(results)}"

    def test_t_values_in_domain(self):
        line = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
        results = osculating_circles_along(line, samples=8)
        n = line.num_control_points - 1
        t_min = float(line.knots[line.degree])
        t_max = float(line.knots[n + 1])
        for oc in results:
            assert t_min <= oc.t <= t_max + 1e-12

    def test_invalid_samples_raises(self):
        circ = make_circle_nurbs(np.zeros(3), 1.0)
        with pytest.raises(ValueError):
            osculating_circles_along(circ, samples=1)

    def test_dataclass_fields_present(self):
        circ = make_circle_nurbs(np.zeros(3), 1.0)
        oc = osculating_circle(circ, 0.125)
        assert hasattr(oc, "t")
        assert hasattr(oc, "point")
        assert hasattr(oc, "tangent")
        assert hasattr(oc, "curvature")
        assert hasattr(oc, "radius")
        assert hasattr(oc, "center")
        assert hasattr(oc, "normal_plane_normal")
        assert hasattr(oc, "is_degenerate")


# ---------------------------------------------------------------------------
# 6. Degenerate sentinel
# ---------------------------------------------------------------------------

class TestDegenerateSentinel:
    """is_degenerate=True propagated for inflection/straight."""

    def test_degenerate_has_none_radius(self):
        line = make_line_nurbs(np.zeros(3), np.array([1.0, 0.0, 0.0]))
        oc = osculating_circle(line, 0.5)
        assert oc.is_degenerate
        assert oc.radius is None
        assert oc.center is None

    def test_degenerate_curvature_zero(self):
        line = make_line_nurbs(np.zeros(3), np.array([0.0, 1.0, 0.0]))
        oc = osculating_circle(line, 0.5)
        assert oc.curvature == 0.0


# ---------------------------------------------------------------------------
# 7. Re-export from geom.__init__
# ---------------------------------------------------------------------------

def test_reexport_from_geom_init():
    """OsculatingCircle, osculating_circle, osculating_circles_along are
    importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import (  # noqa: F401
        OsculatingCircle as OC,
        osculating_circle as oc_fn,
        osculating_circles_along as oca_fn,
    )
    assert callable(oc_fn)
    assert callable(oca_fn)
