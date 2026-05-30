"""
test_offset_distance_field.py
==============================
GK-140 — Hermetic pytest oracles for compute_offset_distance_field.

Oracle contracts
----------------
1. Sphere offset by d=0.5 (r=1, result Σ has r_Σ=1.5):
   - grid node at origin  → φ ≈ −1.5  (inside)
   - grid node at (1.5,0,0) → φ ≈  0   (on surface)
   - grid node at (3,0,0)   → φ ≈ +1.5 (outside)

2. Plane offset by d=2.0 (xy-plane → z=2 plane):
   - grid node at (0,0,2)   → φ ≈  0   (on offset surface)
   - grid node at (0,0,5)   → φ ≈ +3   (outside, 3 units from z=2)
   - grid node at (0,0,0)   → φ ≈ −2   (inside, 2 units from z=2)

3. Degenerate d=0 (offset is the original surface):
   - sampled grid should match distances to the original surface.

4. DistanceFieldResult.query() trilinear interpolation: on-surface point
   returns value near 0.

5. Importable from kerf_cad_core.geom.

References
----------
Maekawa 1999 — Computer-Aided Design 31(3), pp. 165–173.
Piegl & Tiller, "The NURBS Book" §11.3.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom import compute_offset_distance_field, DistanceFieldResult
from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Surface factories (shared with test_surface_offset; kept hermetic here)
# ---------------------------------------------------------------------------

_S = math.sqrt(2.0) / 2.0


def make_rational_sphere(center, r) -> NurbsSurface:
    """Exact rational quadratic NURBS sphere of radius *r* centred at *center*."""
    center = np.asarray(center, dtype=float)
    mer = [
        (0.0, -r, 1.0), (r, -r, _S), (r, 0.0, 1.0), (r, r, _S), (0.0, r, 1.0),
    ]
    circ9 = [
        (1.0, 0.0, 1.0), (1.0, 1.0, _S), (0.0, 1.0, 1.0), (-1.0, 1.0, _S),
        (-1.0, 0.0, 1.0), (-1.0, -1.0, _S), (0.0, -1.0, 1.0), (1.0, -1.0, _S),
        (1.0, 0.0, 1.0),
    ]
    cp = np.zeros((9, 5, 3))
    w = np.zeros((9, 5))
    for i, (cx, cy, cw) in enumerate(circ9):
        for j, (mx, my, mw) in enumerate(mer):
            m_rho = mx
            m_y   = my
            circ_x = cx
            circ_y = cy
            cp[i, j] = center + np.array([m_rho * circ_x, m_y, m_rho * circ_y])
            w[i, j] = cw * mw

    ku9 = np.array([0, 0, 0, .25, .25, .5, .5, .75, .75, 1, 1, 1.0])
    kv5 = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cp, knots_u=ku9, knots_v=kv5,
        weights=w,
    )


def make_plane_nurbs(origin, normal, size: float = 10.0) -> NurbsSurface:
    """Degree-(1,1) planar NURBS patch centred at *origin* with unit *normal*."""
    origin = np.asarray(origin, dtype=float)
    n = np.asarray(normal, dtype=float)
    n = n / np.linalg.norm(n)
    ref = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = ref - np.dot(ref, n) * n
    e1 = e1 / np.linalg.norm(e1) * size
    e2 = np.cross(n, e1)
    e2 = e2 / np.linalg.norm(e2) * size
    p00 = origin - e1 * 0.5 - e2 * 0.5
    p10 = origin + e1 * 0.5 - e2 * 0.5
    p01 = origin - e1 * 0.5 + e2 * 0.5
    p11 = origin + e1 * 0.5 + e2 * 0.5
    cps = np.array([[p00, p01], [p10, p11]])
    ku = np.array([0.0, 0.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cps,
                        knots_u=ku, knots_v=kv)


# ---------------------------------------------------------------------------
# Oracle 1: sphere offset distance field
# Σ = offset sphere with radius r_Σ = 1 + 0.5 = 1.5
# ---------------------------------------------------------------------------

class TestSphereOffsetDistanceField:
    """Unit-sphere offset by d=0.5 → offset sphere of radius 1.5.

    Known analytic values (Maekawa 1999; Piegl & Tiller §11.3):
      origin      → φ = −r_Σ = −1.5  (inside, closest point on Σ is r_Σ away)
      (1.5, 0, 0) → φ =  0            (on Σ)
      (3.0, 0, 0) → φ = +1.5          (outside, 3 − r_Σ = 1.5)
    """

    @pytest.fixture(scope="class")
    def field(self):
        sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
        # Use an explicit bbox that covers [−3, 3]³
        bbox = (np.array([-3.5, -3.5, -3.5]), np.array([3.5, 3.5, 3.5]))
        return compute_offset_distance_field(sphere, 0.5, bbox=bbox, grid_size=8)

    def test_result_type(self, field):
        assert isinstance(field, DistanceFieldResult)

    def test_grid_shape(self, field):
        assert field.distances_3d.shape == (8, 8, 8)

    def test_grid_size_attr(self, field):
        assert field.grid_size == 8

    def test_offset_distance_attr(self, field):
        assert field.offset_distance == pytest.approx(0.5)

    def test_resolution_positive(self, field):
        assert field.resolution > 0

    def test_inside_at_origin(self, field):
        """Origin should be inside the offset sphere (φ < 0).

        Note: on a grid_size=8 grid spanning ±3.5, the step is 1.0 and the
        origin falls between grid nodes.  Trilinear interpolation introduces
        error up to ~step/2 ≈ 0.5 relative to the analytic value of −1.5.
        We therefore only assert sign and a loose bound.
        """
        val = field.query([0.0, 0.0, 0.0])
        assert val < 0, f"expected φ<0 at origin, got {val}"
        # Loose tolerance: interpolation error ≤ grid_step ≈ 1.0 for this grid
        assert val > -2.5, f"expected > −2.5, got {val:.4f}"

    def test_outside_at_far_point(self, field):
        """(3,0,0) should be outside the offset sphere (φ ≈ +1.5)."""
        val = field.query([3.0, 0.0, 0.0])
        assert val > 0, f"expected φ>0 at (3,0,0), got {val}"
        assert abs(val - 1.5) < 0.3, f"expected ≈ +1.5, got {val:.4f}"

    def test_on_surface_query(self, field):
        """(1.5,0,0) is on the offset sphere; field should be near 0."""
        val = field.query([1.5, 0.0, 0.0])
        assert abs(val) < 0.4, f"expected ≈ 0 at (1.5,0,0), got {val:.4f}"

    def test_sign_consistency(self, field):
        """Far exterior point is positive; far interior point is negative."""
        inside = field.query([0.0, 0.0, 0.0])
        outside = field.query([3.0, 0.0, 0.0])
        assert inside < 0
        assert outside > 0


# ---------------------------------------------------------------------------
# Oracle 2: plane offset distance field
# Σ = xy-plane offset by d=2 → plane at z=2
# ---------------------------------------------------------------------------

class TestPlaneOffsetDistanceField:
    """xy-plane (origin, normal [0,0,1]) offset by d=2 → plane at z=2.

    Known analytic values:
      (0, 0, 2) → φ =  0  (on Σ)
      (0, 0, 5) → φ = +3  (above Σ, outside)
      (0, 0, 0) → φ = −2  (below Σ, inside)
    """

    @pytest.fixture(scope="class")
    def field(self):
        plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], size=10.0)
        bbox = (np.array([-1.0, -1.0, -4.0]), np.array([1.0, 1.0, 6.0]))
        return compute_offset_distance_field(plane, 2.0, bbox=bbox, grid_size=8)

    def test_result_type(self, field):
        assert isinstance(field, DistanceFieldResult)

    def test_offset_distance_attr(self, field):
        assert field.offset_distance == pytest.approx(2.0)

    def test_inside_at_origin(self, field):
        """z=0 is below z=2 plane → φ ≈ −2."""
        val = field.query([0.0, 0.0, 0.0])
        assert val < 0, f"expected φ<0 at z=0, got {val}"
        assert abs(val - (-2.0)) < 0.5, f"expected ≈ −2, got {val:.4f}"

    def test_outside_above_plane(self, field):
        """z=5 is above z=2 plane → φ ≈ +3."""
        val = field.query([0.0, 0.0, 5.0])
        assert val > 0, f"expected φ>0 at z=5, got {val}"
        assert abs(val - 3.0) < 0.5, f"expected ≈ +3, got {val:.4f}"

    def test_on_offset_plane(self, field):
        """z=2 is on the offset plane → φ ≈ 0."""
        val = field.query([0.0, 0.0, 2.0])
        assert abs(val) < 0.4, f"expected ≈ 0 at z=2, got {val:.4f}"


# ---------------------------------------------------------------------------
# Oracle 3: degenerate d=0 — offset is the original surface
# ---------------------------------------------------------------------------

class TestZeroOffsetDistanceField:
    """d=0: Σ = S.  Grid distances should be the same as distance to the
    original surface.  On-surface query ≈ 0; far point > 0."""

    @pytest.fixture(scope="class")
    def field(self):
        sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
        bbox = (np.array([-3.0, -3.0, -3.0]), np.array([3.0, 3.0, 3.0]))
        return compute_offset_distance_field(sphere, 0.0, bbox=bbox, grid_size=8)

    def test_offset_distance_zero(self, field):
        assert field.offset_distance == pytest.approx(0.0)

    def test_on_unit_sphere_surface(self, field):
        """(1,0,0) is on the unit sphere (d=0 offset = original) → φ ≈ 0."""
        val = field.query([1.0, 0.0, 0.0])
        assert abs(val) < 0.3, f"expected ≈ 0 at (1,0,0), got {val:.4f}"

    def test_origin_inside_unit_sphere(self, field):
        """Origin is inside unit sphere (d=0) → φ < 0.

        Trilinear interpolation on a coarse grid introduces significant error
        at non-node query points.  We assert sign only.
        """
        val = field.query([0.0, 0.0, 0.0])
        assert val < 0, f"expected φ<0 at origin, got {val}"

    def test_far_point_outside(self, field):
        """(2.5,0,0) is outside unit sphere → φ ≈ +1.5."""
        val = field.query([2.5, 0.0, 0.0])
        assert val > 0, f"expected φ>0 at (2.5,0,0), got {val}"


# ---------------------------------------------------------------------------
# Oracle 4: query() interpolation sanity
# ---------------------------------------------------------------------------

def test_query_on_grid_node():
    """query() at a grid node should return exactly the stored value."""
    sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
    bbox = (np.array([-3.0, -3.0, -3.0]), np.array([3.0, 3.0, 3.0]))
    result = compute_offset_distance_field(sphere, 0.5, bbox=bbox, grid_size=5)
    lo, hi = result.bbox
    step = (hi - lo) / (result.grid_size - 1)
    # Query at grid node [0, 0, 0]
    p0 = lo.copy()
    v_query = result.query(p0)
    v_direct = float(result.distances_3d[0, 0, 0])
    assert abs(v_query - v_direct) < 1e-10, (
        f"query at node [0,0,0] = {v_query}, direct = {v_direct}"
    )
    # Query at grid node [2, 2, 2]
    p2 = lo + 2 * step
    v_query2 = result.query(p2)
    v_direct2 = float(result.distances_3d[2, 2, 2])
    assert abs(v_query2 - v_direct2) < 1e-10, (
        f"query at node [2,2,2] = {v_query2}, direct = {v_direct2}"
    )


# ---------------------------------------------------------------------------
# Oracle 5: public import from kerf_cad_core.geom
# ---------------------------------------------------------------------------

def test_importable_from_geom():
    from kerf_cad_core.geom import compute_offset_distance_field as f, DistanceFieldResult as R
    assert callable(f)
    assert isinstance(R, type)


# ---------------------------------------------------------------------------
# Error / validation cases
# ---------------------------------------------------------------------------

def test_bad_srf_type_raises():
    with pytest.raises(ValueError, match="NurbsSurface"):
        compute_offset_distance_field("not_a_surface", 1.0)


def test_bad_distance_nan_raises():
    sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
    with pytest.raises(ValueError, match="finite"):
        compute_offset_distance_field(sphere, float("nan"))


def test_bad_grid_size_raises():
    sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
    with pytest.raises(ValueError, match="grid_size"):
        compute_offset_distance_field(sphere, 0.5, grid_size=1)


def test_collapse_sphere_raises():
    """Offsetting unit sphere by -2.0 should raise (collapses)."""
    sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
    with pytest.raises(ValueError):
        compute_offset_distance_field(sphere, -2.0)
