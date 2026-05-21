"""
test_mold_parting_line.py
=========================
GK-118: Hermetic pytest oracle for parting_line().

Spec oracle: the parting line of a unit sphere pulled along Z is the equator
— all returned points satisfy:
  • z  ≈ 0       (within tol)
  • sqrt(x²+y²) ≈ r  (within tol, i.e. they lie on the equatorial circle)

All tests are hermetic (pure-Python, no DB, no OCC required).
"""

from __future__ import annotations

import math
from typing import List

import pytest

from kerf_cad_core.geom.mold import parting_line, Point3
from kerf_cad_core.geom.brep_build import sphere_to_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_equator(pts: List[Point3], radius: float, tol: float = 0.05) -> None:
    """Assert every point lies on the equatorial circle of the sphere."""
    assert len(pts) > 0, "parting_line returned no points"
    for p in pts:
        x, y, z = p[0], p[1], p[2]
        assert abs(z) < tol, (
            f"z={z:.6f} too far from equator (tol={tol}); "
            f"point = {p}"
        )
        r_xy = math.hypot(x, y)
        assert abs(r_xy - radius) < tol, (
            f"radial distance r_xy={r_xy:.6f} != radius={radius} (tol={tol}); "
            f"point = {p}"
        )


# ---------------------------------------------------------------------------
# GK-118 oracle tests
# ---------------------------------------------------------------------------

class TestPartingLineSphere:
    """Parting line of a sphere pulled along Z is the equator."""

    def test_unit_sphere_pull_z(self):
        """Unit sphere at origin, pull [0,0,1] → all pts at z≈0, r_xy≈1."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        pts = parting_line(body, [0.0, 0.0, 1.0])
        _check_equator(pts, radius=1.0, tol=0.05)

    def test_unit_sphere_pull_neg_z(self):
        """Pulling in −Z direction should also yield the equator."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        pts = parting_line(body, [0.0, 0.0, -1.0])
        _check_equator(pts, radius=1.0, tol=0.05)

    def test_radius_two_sphere(self):
        """Radius-2 sphere: equator points should have r_xy ≈ 2."""
        body = sphere_to_body([0.0, 0.0, 0.0], 2.0)
        pts = parting_line(body, [0.0, 0.0, 1.0])
        _check_equator(pts, radius=2.0, tol=0.1)

    def test_offset_center_sphere(self):
        """Sphere centered at (5, 3, 1): equator at z=1, r_xy from (5,3) ≈ r."""
        cx, cy, cz, r = 5.0, 3.0, 1.0, 1.5
        body = sphere_to_body([cx, cy, cz], r)
        pts = parting_line(body, [0.0, 0.0, 1.0])
        assert len(pts) > 0
        for p in pts:
            x, y, z = p[0], p[1], p[2]
            assert abs(z - cz) < 0.1, f"z={z:.4f} not ≈ cz={cz}"
            r_xy = math.hypot(x - cx, y - cy)
            assert abs(r_xy - r) < 0.1, f"r_xy={r_xy:.4f} not ≈ r={r}"

    def test_non_unit_pull_direction(self):
        """Pull direction need not be unit length."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        pts = parting_line(body, [0.0, 0.0, 10.0])  # scaled Z
        _check_equator(pts, radius=1.0, tol=0.05)

    def test_returns_list_of_3d_points(self):
        """Each returned element is a 3-element float sequence."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        pts = parting_line(body, [0.0, 0.0, 1.0])
        assert isinstance(pts, list)
        for p in pts:
            assert len(p) == 3, f"Expected 3-vector, got length {len(p)}"
            assert all(isinstance(c, float) for c in p), (
                f"Expected floats, got {[type(c) for c in p]}"
            )

    def test_zero_pull_raises(self):
        """A zero pull_direction vector must raise ValueError."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        with pytest.raises(ValueError, match="non-zero"):
            parting_line(body, [0.0, 0.0, 0.0])

    def test_exported_from_geom_init(self):
        """parting_line must be importable from the public geom façade."""
        from kerf_cad_core.geom import parting_line as pl  # noqa: F401
        assert callable(pl)
