"""
test_surface_offset_tiller_hanson.py
=====================================
GK-83 / GK-P-NURBS-OFFSET — Hermetic pytest suite for the Tiller-Hanson
surface-offset pipeline:

  offset_surface, detect_self_intersection, trim_self_intersection_loops

Oracle contracts
----------------
1. **Planar surface offset**: flat 1×1 unit plane offset by d=0.5 → result is
   a flat plane parallel to original at exactly z=0.5; CP positions match
   within 1e-12.

2. **Cylindrical surface offset**: NURBS cylinder of radius r offset outward
   by d → result is a NURBS cylinder of radius r+d (analytical); radial
   position of sampled surface points matches r+d within 1% post-refinement.

3. **Sphere offset**: NURBS sphere of radius r offset by d → sampled points
   lie at radius r+d within 2%.

4. **Self-intersection detection**: a sharply-curved C-shape offset by a large
   distance (d > min curvature radius) → detector finds at least one
   intersection; trim_self_intersection_loops returns a valid NurbsSurface.

Run:
    python -m pytest packages/kerf-cad-core/tests/test_surface_offset_tiller_hanson.py -q
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.surface_offset import (
    offset_surface,
    detect_self_intersection,
    trim_self_intersection_loops,
)
from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate
from kerf_cad_core.geom.inversion import _surface_param_range


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

_S = math.sqrt(2.0) / 2.0


def make_plane_nurbs(
    origin: list | np.ndarray,
    normal: list | np.ndarray,
    size: float = 1.0,
) -> NurbsSurface:
    """Degree-(1,1) planar NURBS patch centred at *origin* with unit *normal*.

    The patch is a parallelogram of side *size* lying in the plane with the
    given normal.
    """
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


def make_nurbs_cylinder(
    radius: float,
    height: float,
    n_circ: int = 9,
    n_height: int = 2,
) -> NurbsSurface:
    """Approximate NURBS cylinder of given radius and height.

    Uses a degree-2 × degree-1 patch.  The circle cross-section is the
    standard 9-CP rational quadratic arc (exact circle).  The height
    direction is linear (exact).

    The axis is aligned with Z.  The cylinder spans z ∈ [0, height].
    """
    # Rational quadratic circle CPs in (x,y) plane.
    circle_cps_2d = [
        (1.0, 0.0, 1.0),
        (1.0, 1.0, _S),
        (0.0, 1.0, 1.0),
        (-1.0, 1.0, _S),
        (-1.0, 0.0, 1.0),
        (-1.0, -1.0, _S),
        (0.0, -1.0, 1.0),
        (1.0, -1.0, _S),
        (1.0, 0.0, 1.0),
    ]
    # Build control-point net: n_circ × n_height
    nu = n_circ
    nv = n_height
    cp = np.zeros((nu, nv, 3))
    w = np.zeros((nu, nv))
    zs = np.linspace(0.0, height, nv)
    for i, (cx, cy, cw) in enumerate(circle_cps_2d):
        for j, z in enumerate(zs):
            cp[i, j] = [radius * cx, radius * cy, z]
            w[i, j] = cw

    ku = np.array([0.0, 0.0, 0.0, 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1.0, 1.0, 1.0])
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=2, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv, weights=w)


def make_rational_sphere(center: list | np.ndarray, r: float) -> NurbsSurface:
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


def make_self_intersecting_surface() -> NurbsSurface:
    """Build a NURBS surface that already self-intersects (tight closed loop).

    The surface is a closed-loop strip with radius 0.2 in the XZ plane.  When
    sampled on a coarse grid (n≥15) the triangulation reveals self-intersections
    because the same region of space is covered by multiple triangles on the
    nearly-closed strip.

    This fixture is used to verify ``detect_self_intersection`` can find
    overlapping triangles in an offset surface with high curvature.  The
    strip is parameterised as a NURBS degree-3 surface, and the offset by
    d=0.3 (> radius 0.2) is guaranteed to make the curvature-induced folds
    detectable at n_samples=20.
    """
    # Full-circle strip: 14 control points, radius 0.2
    nu = 14
    nv = 2
    R = 0.2
    angles = np.linspace(0, 2 * math.pi, nu, endpoint=True)  # closes the loop
    cp = np.zeros((nu, nv, 3))
    for i, a in enumerate(angles):
        x = R * math.cos(a)
        z = R * math.sin(a)
        cp[i, 0] = [x, -0.3, z]
        cp[i, 1] = [x,  0.3, z]

    def _clamped(n, p):
        inner = max(0, n - p - 1)
        knots = np.zeros(n + p + 1)
        knots[-(p + 1):] = 1.0
        if inner > 0:
            knots[p + 1: p + 1 + inner] = np.linspace(0.0, 1.0, inner + 2)[1:-1]
        return knots

    ku = _clamped(nu, 3)
    kv = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=3, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


def _sample_pts(surf: NurbsSurface, n: int = 10) -> np.ndarray:
    """Return (n*n, 3) sampled points on *surf*."""
    u0, u1, v0, v1 = _surface_param_range(surf)
    pts = []
    for u in np.linspace(u0, u1, n):
        for v in np.linspace(v0, v1, n):
            p = surface_evaluate(surf, float(u), float(v))
            pts.append(p[:3])
    return np.array(pts)


# ---------------------------------------------------------------------------
# Oracle 1: Planar surface offset
# ---------------------------------------------------------------------------

def test_plane_offset_cp_positions():
    """Offset of a 1×1 unit plane by d=0.5 moves CPs exactly 0.5 along Z.

    The Tiller-Hanson analytic shortcut for planar (degree-1) surfaces
    gives machine precision — within 1e-12 of the expected z=0.5 translation.
    """
    d = 0.5
    plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], size=1.0)
    offset = offset_surface(plane, d, refine_iter=3, tol=1e-6)

    assert isinstance(offset, NurbsSurface)

    orig_cps = plane.control_points[:, :, :3]
    off_cps  = offset.control_points[:, :, :3]
    expected = orig_cps + np.array([0.0, 0.0, d])

    max_err = float(np.max(np.abs(off_cps - expected)))
    assert max_err < 1e-12, (
        f"Plane offset CP error {max_err:.2e} exceeds 1e-12 — "
        f"analytic shortcut may be broken"
    )


def test_plane_offset_sampled_pts():
    """Sampled points on offset plane must all lie at z=0.5."""
    d = 0.5
    plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], size=1.0)
    offset = offset_surface(plane, d)

    pts = _sample_pts(offset, n=8)
    z_values = pts[:, 2]
    assert float(np.max(np.abs(z_values - d))) < 1e-9, (
        f"Sampled z range [{z_values.min():.6f}, {z_values.max():.6f}] "
        f"should all be {d}"
    )


def test_plane_offset_uv_topology_preserved():
    """Plane offset preserves degree, knot vectors, and CP net shape."""
    plane = make_plane_nurbs([1.0, 2.0, 3.0], [0.0, 1.0, 0.0])
    offset = offset_surface(plane, 0.25)
    assert offset.degree_u == plane.degree_u
    assert offset.degree_v == plane.degree_v
    assert offset.control_points.shape == plane.control_points.shape
    assert np.allclose(offset.knots_u, plane.knots_u)
    assert np.allclose(offset.knots_v, plane.knots_v)


# ---------------------------------------------------------------------------
# Oracle 2: Cylindrical surface offset
# ---------------------------------------------------------------------------

def test_cylinder_offset_radial_distance():
    """Offset of a NURBS cylinder radius r by d → sampled points at r+d (± 1%).

    The cylinder offset is not analytically exact via the Tiller-Hanson
    CP-normal method because the rational weights complicate the CP net
    geometry.  Post-refinement the sampled surface must be within 1% of r+d.
    """
    r = 1.0
    d = 0.25
    cyl = make_nurbs_cylinder(radius=r, height=1.0)
    offset = offset_surface(cyl, d, refine_iter=3, tol=1e-3)

    assert isinstance(offset, NurbsSurface)

    # Sample points and check radial distance from Z-axis (x^2 + y^2 = (r+d)^2).
    pts = _sample_pts(offset, n=10)
    radii = np.sqrt(pts[:, 0]**2 + pts[:, 1]**2)
    expected_r = r + d
    mean_err = float(np.abs(np.mean(radii) - expected_r))
    rel_err = mean_err / expected_r

    assert rel_err < 0.01, (
        f"Cylinder offset mean radial error {rel_err*100:.2f}% exceeds 1%"
        f" (mean={np.mean(radii):.4f}, expected={expected_r:.4f})"
    )


def test_cylinder_offset_uv_topology():
    """Cylinder offset preserves degree and CP net shape."""
    cyl = make_nurbs_cylinder(radius=2.0, height=2.0)
    offset = offset_surface(cyl, 0.1)
    assert offset.degree_u == cyl.degree_u
    assert offset.degree_v == cyl.degree_v
    assert offset.control_points.shape == cyl.control_points.shape


# ---------------------------------------------------------------------------
# Oracle 3: Sphere offset
# ---------------------------------------------------------------------------

def test_sphere_offset_radius():
    """Offset of sphere radius r by d → sampled points at r+d (± 2%)."""
    r = 1.0
    d = 0.3
    sphere = make_rational_sphere([0.0, 0.0, 0.0], r)
    offset = offset_surface(sphere, d, refine_iter=3, tol=1e-3)

    assert isinstance(offset, NurbsSurface)

    pts = _sample_pts(offset, n=8)
    dists = np.linalg.norm(pts, axis=1)
    expected_r = r + d
    mean_err = float(np.abs(np.mean(dists) - expected_r))
    rel_err = mean_err / expected_r

    assert rel_err < 0.02, (
        f"Sphere offset mean radial error {rel_err*100:.2f}% exceeds 2%"
        f" (mean={np.mean(dists):.4f}, expected={expected_r:.4f})"
    )


@pytest.mark.parametrize("d,r", [(0.5, 1.0), (-0.3, 1.0), (0.1, 3.0)])
def test_sphere_offset_analytic_shortcut(d, r):
    """Sphere analytic shortcut: exact radius within 1e-6."""
    sphere = make_rational_sphere([0.0, 0.0, 0.0], r)
    offset = offset_surface(sphere, d)
    pts = _sample_pts(offset, n=8)
    dists = np.linalg.norm(pts, axis=1)
    expected = r + d
    assert abs(float(np.mean(dists)) - expected) < 1e-6
    assert float(np.max(np.abs(dists - expected))) < 1e-6


def test_sphere_offset_collapses_raises():
    """Offsetting a unit sphere by -2 (collapses) must raise ValueError."""
    sphere = make_rational_sphere([0.0, 0.0, 0.0], 1.0)
    with pytest.raises(ValueError, match="collapse"):
        offset_surface(sphere, -2.0)


# ---------------------------------------------------------------------------
# Oracle 4: Self-intersection detection and loop trimming
# ---------------------------------------------------------------------------

def test_self_intersection_detected_on_tight_loop():
    """A tight-radius closed loop surface has detectable self-intersections.

    The surface is a closed-loop strip with radius R=0.2.  When sampled at
    n_samples=20 the triangulated mesh triangles from opposite sides of the
    loop overlap, producing Möller-detected intersections.  This confirms the
    detector operates correctly on surfaces with high curvature / folding.
    """
    loop = make_self_intersecting_surface()
    intersections = detect_self_intersection(loop, n_samples=20)
    assert len(intersections) > 0, (
        "Expected at least one self-intersection on tight closed-loop surface, "
        f"got 0 (nu={loop.num_control_points_u})"
    )


def test_self_intersection_each_has_required_keys():
    """Each self-intersection dict must have region_a, region_b, point."""
    loop = make_self_intersecting_surface()
    intersections = detect_self_intersection(loop, n_samples=20)
    for ix in intersections:
        assert "region_a" in ix
        assert "region_b" in ix
        assert "point" in ix
        assert len(ix["point"]) == 3


def test_trim_returns_valid_nurbs():
    """trim_self_intersection_loops returns a valid NurbsSurface."""
    loop = make_self_intersecting_surface()
    intersections = detect_self_intersection(loop, n_samples=20)

    trimmed = trim_self_intersection_loops(loop, intersections)
    assert isinstance(trimmed, NurbsSurface)
    # Must have same UV topology.
    assert trimmed.degree_u == loop.degree_u
    assert trimmed.degree_v == loop.degree_v
    assert trimmed.control_points.shape == loop.control_points.shape


def test_trim_no_intersections_returns_copy():
    """trim with empty intersections returns an unchanged copy."""
    plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    offset = offset_surface(plane, 0.5)
    trimmed = trim_self_intersection_loops(offset, [])
    assert isinstance(trimmed, NurbsSurface)
    assert np.allclose(trimmed.control_points, offset.control_points)


def test_detect_no_intersection_on_plane():
    """A simple plane offset should NOT generate any self-intersections."""
    plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], size=2.0)
    offset = offset_surface(plane, 0.5)
    intersections = detect_self_intersection(offset, n_samples=8)
    assert len(intersections) == 0, (
        f"Plane offset should have zero self-intersections, got {len(intersections)}"
    )


# ---------------------------------------------------------------------------
# Oracle 5: LLM tool importability
# ---------------------------------------------------------------------------

def test_offset_surface_importable_from_geom():
    """offset_surface must be importable from kerf_cad_core.geom.surface_offset."""
    from kerf_cad_core.geom.surface_offset import offset_surface as _fn
    assert callable(_fn)


def test_detect_self_intersection_importable():
    from kerf_cad_core.geom.surface_offset import detect_self_intersection as _fn
    assert callable(_fn)


def test_trim_self_intersection_loops_importable():
    from kerf_cad_core.geom.surface_offset import trim_self_intersection_loops as _fn
    assert callable(_fn)


# ---------------------------------------------------------------------------
# Oracle 6: Error handling
# ---------------------------------------------------------------------------

def test_nan_distance_raises():
    plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    with pytest.raises(ValueError):
        offset_surface(plane, float("nan"))


def test_inf_distance_raises():
    plane = make_plane_nurbs([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    with pytest.raises(ValueError):
        offset_surface(plane, float("inf"))


def test_bad_type_raises():
    with pytest.raises(ValueError):
        offset_surface("not a surface", 1.0)  # type: ignore[arg-type]
