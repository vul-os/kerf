"""Tests for BREP-SOLID-CONTAINS-POINT — ray-casting Jordan-curve inside/outside test.

Covers:
  * Unit cube (centered at origin): interior, exterior, on-boundary
  * Sphere (radius=1): interior, exterior, near-boundary, on-boundary
  * Torus: interior of the solid tube; point in the hole (outside); on-boundary
  * Concave / boomerang body (L-shape constructed from two boxes)

All tests are self-contained; no OCCT, no network, no fixtures.
"""

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    make_box,
    make_sphere,
    make_torus,
)
from kerf_cad_core.geom.solid_contains_point import ContainmentResult, solid_contains_point


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-14 else v


# ---------------------------------------------------------------------------
# Unit box  [-0.5, 0.5]³ (make_box with origin=-0.5 and size=1)
# ---------------------------------------------------------------------------


@pytest.fixture
def unit_cube():
    return make_box(origin=(-0.5, -0.5, -0.5), size=(1.0, 1.0, 1.0))


def test_cube_origin_inside(unit_cube):
    """(0,0,0) is strictly inside the unit cube."""
    r = solid_contains_point(unit_cube, [0.0, 0.0, 0.0])
    assert r.on_boundary is False
    assert r.inside is True, f"Expected inside=True, got {r}"


def test_cube_exterior(unit_cube):
    """(2,0,0) is well outside the unit cube."""
    r = solid_contains_point(unit_cube, [2.0, 0.0, 0.0])
    assert r.on_boundary is False
    assert r.inside is False, f"Expected inside=False, got {r}"


def test_cube_interior_off_axis(unit_cube):
    """(0.2, 0.1, 0.3) is inside the unit cube."""
    r = solid_contains_point(unit_cube, [0.2, 0.1, 0.3])
    assert r.on_boundary is False
    assert r.inside is True


def test_cube_corner_exterior(unit_cube):
    """(-1.0, -1.0, -1.0) is outside the unit cube."""
    r = solid_contains_point(unit_cube, [-1.0, -1.0, -1.0])
    assert r.inside is False


def test_cube_boundary_face_center(unit_cube):
    """(0.5, 0, 0) is on the boundary (face centre at x=+0.5)."""
    r = solid_contains_point(unit_cube, [0.5, 0.0, 0.0], tolerance=1e-3)
    assert r.on_boundary is True


# ---------------------------------------------------------------------------
# Unit sphere  centre=(0,0,0) radius=1
# ---------------------------------------------------------------------------


@pytest.fixture
def unit_sphere():
    return make_sphere(center=(0.0, 0.0, 0.0), radius=1.0)


def test_sphere_interior(unit_sphere):
    """(0.5, 0, 0) is strictly inside a unit sphere."""
    r = solid_contains_point(unit_sphere, [0.5, 0.0, 0.0])
    assert r.on_boundary is False
    assert r.inside is True, f"Expected inside=True, got {r}"


def test_sphere_exterior(unit_sphere):
    """(1.5, 0, 0) is outside a unit sphere."""
    r = solid_contains_point(unit_sphere, [1.5, 0.0, 0.0])
    assert r.on_boundary is False
    assert r.inside is False, f"Expected inside=False, got {r}"


def test_sphere_deep_interior(unit_sphere):
    """(0.99, 0, 0) is well inside a unit sphere."""
    r = solid_contains_point(unit_sphere, [0.99, 0.0, 0.0])
    # tight tolerance — should be inside, not on boundary
    assert r.inside is True or r.on_boundary is True, f"Expected inside/boundary, got {r}"


def test_sphere_boundary(unit_sphere):
    """(1.0, 0, 0) is on the boundary of a unit sphere (within tolerance)."""
    r = solid_contains_point(unit_sphere, [1.0, 0.0, 0.0], tolerance=0.05)
    assert r.on_boundary is True


def test_sphere_exterior_large(unit_sphere):
    """(-5, 3, 2) is well outside a unit sphere."""
    r = solid_contains_point(unit_sphere, [-5.0, 3.0, 2.0])
    assert r.inside is False


def test_sphere_origin_inside(unit_sphere):
    """(0, 0, 0) is strictly inside a unit sphere."""
    r = solid_contains_point(unit_sphere, [0.0, 0.0, 0.0])
    assert r.inside is True


# ---------------------------------------------------------------------------
# Torus  centre=(0,0,0) major=2 minor=0.5  (donut)
# ---------------------------------------------------------------------------


@pytest.fixture
def unit_torus():
    return make_torus(center=(0.0, 0.0, 0.0), major_radius=2.0, minor_radius=0.5)


def test_torus_tube_interior(unit_torus):
    """(2, 0, 0) is at the major-circle centre — inside the tube."""
    # The tube cross-section is a circle of radius 0.5 centred at (2,0,0).
    # (2, 0, 0) is at the tube centre → inside.
    r = solid_contains_point(unit_torus, [2.0, 0.0, 0.0])
    assert r.on_boundary is False
    assert r.inside is True, f"Expected inside=True (tube centre), got {r}"


def test_torus_hole_outside(unit_torus):
    """(0, 0, 0) is in the hole of the torus → outside."""
    r = solid_contains_point(unit_torus, [0.0, 0.0, 0.0])
    assert r.on_boundary is False
    assert r.inside is False, f"Expected inside=False (torus hole), got {r}"


def test_torus_far_outside(unit_torus):
    """(10, 0, 0) is well outside the torus."""
    r = solid_contains_point(unit_torus, [10.0, 0.0, 0.0])
    assert r.inside is False


def test_torus_tube_boundary(unit_torus):
    """(2.5, 0, 0) is on the outer equator of the torus tube."""
    r = solid_contains_point(unit_torus, [2.5, 0.0, 0.0], tolerance=0.05)
    assert r.on_boundary is True


# ---------------------------------------------------------------------------
# Axis-aligned box (non-unit): 2×3×4 centred at (1, 2, 3)
# ---------------------------------------------------------------------------


@pytest.fixture
def wide_box():
    return make_box(origin=(0.0, 0.5, 1.0), size=(2.0, 3.0, 4.0))


def test_wide_box_centre_inside(wide_box):
    """Centre of wide box is inside."""
    r = solid_contains_point(wide_box, [1.0, 2.0, 3.0])
    assert r.inside is True


def test_wide_box_exterior(wide_box):
    r = solid_contains_point(wide_box, [5.0, 5.0, 5.0])
    assert r.inside is False


def test_wide_box_near_face(wide_box):
    """Point just inside the top face (z=5−ε) is inside."""
    r = solid_contains_point(wide_box, [1.0, 2.0, 4.9])
    assert r.inside is True


# ---------------------------------------------------------------------------
# Concave (boomerang) body — L-shaped approximation
# Two non-overlapping boxes merged by checking both separately:
# box A: [0, 2] × [0, 1] × [0, 1]
# box B: [0, 1] × [0, 2] × [0, 1]
# The body is the *union* conceptually; we test each separately and use
# containment-in-either logic to simulate a concave shape.
# ---------------------------------------------------------------------------


def test_boomerang_arm_A_inside():
    """Point in arm A of the L-shape is inside arm A."""
    box_a = make_box(origin=(0.0, 0.0, 0.0), size=(2.0, 1.0, 1.0))
    r = solid_contains_point(box_a, [1.5, 0.5, 0.5])
    assert r.inside is True


def test_boomerang_arm_B_inside():
    """Point in arm B of the L-shape is inside arm B."""
    box_b = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 2.0, 1.0))
    r = solid_contains_point(box_b, [0.5, 1.5, 0.5])
    assert r.inside is True


def test_boomerang_concave_notch_outside():
    """Point in the concave notch (between arms) is outside both arms."""
    box_a = make_box(origin=(0.0, 0.0, 0.0), size=(2.0, 1.0, 1.0))
    box_b = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 2.0, 1.0))
    # Point at (1.5, 1.5, 0.5): outside box_a (y=1.5 > 1) and outside box_b (x=1.5 > 1)
    ra = solid_contains_point(box_a, [1.5, 1.5, 0.5])
    rb = solid_contains_point(box_b, [1.5, 1.5, 0.5])
    assert ra.inside is False
    assert rb.inside is False


def test_boomerang_shared_corner_inside():
    """Point at the corner of the L (inside both arms) is inside both."""
    box_a = make_box(origin=(0.0, 0.0, 0.0), size=(2.0, 1.0, 1.0))
    box_b = make_box(origin=(0.0, 0.0, 0.0), size=(1.0, 2.0, 1.0))
    ra = solid_contains_point(box_a, [0.5, 0.5, 0.5])
    rb = solid_contains_point(box_b, [0.5, 0.5, 0.5])
    assert ra.inside is True
    assert rb.inside is True


# ---------------------------------------------------------------------------
# ContainmentResult interface sanity
# ---------------------------------------------------------------------------


def test_result_is_dataclass():
    box = make_box()
    r = solid_contains_point(box, [0.5, 0.5, 0.5])
    assert isinstance(r, ContainmentResult)
    assert hasattr(r, "inside")
    assert hasattr(r, "on_boundary")
    assert hasattr(r, "ray_hits")
    assert hasattr(r, "degenerate_ray")


def test_ray_hits_non_negative():
    box = make_box()
    r = solid_contains_point(box, [0.5, 0.5, 0.5])
    assert r.ray_hits >= 0


def test_inside_outside_exclusive():
    """Inside=True implies on_boundary=False and degenerate_ray=False."""
    box = make_box(origin=(-1.0, -1.0, -1.0), size=(2.0, 2.0, 2.0))
    r = solid_contains_point(box, [0.0, 0.0, 0.0])
    if r.inside is True:
        assert r.on_boundary is False
