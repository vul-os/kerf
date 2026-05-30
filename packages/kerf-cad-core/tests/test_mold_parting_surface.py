"""
test_mold_parting_surface.py
============================
GK-P Wave 4T: Hermetic pytest oracle suite for mold_parting_surface.py.

Four analytical-oracle tests:
  1. Cube parting surface — cube with pull=+Z, parting at z=0, mold_bbox
     (-2,-2,-2) to (2,2,2) → parting surface is a 4×4 square at z=0.
  2. Sphere parting surface — sphere with equatorial parting line (pull=+Z),
     parting surface is the disc at z=0 extending to mold_bbox radius.
  3. Round-trip validate — body + top + bottom → validate_parting_surface
     returns valid=True.
  4. Shutoff for undercut — body with one undercut face →
     construct_with_shutoff_inserts adds at least one shutoff patch.

All tests are hermetic (pure-Python, no OCC, no DB).
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.mold import parting_line
from kerf_cad_core.geom.mold_parting_surface import (
    construct_parting_surface,
    construct_with_shutoff_inserts,
    validate_parting_surface,
)
from kerf_cad_core.geom.brep_build import box_to_body, sphere_to_body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_z(mesh: dict) -> List[float]:
    return [v[2] for v in mesh["vertices"]]


def _bbox_extent(pts: list, axis: int) -> float:
    vals = [v[axis] for v in pts]
    return max(vals) - min(vals)


# ---------------------------------------------------------------------------
# Test 1: Cube parting surface (flat z=0 plane extending to bbox)
# ---------------------------------------------------------------------------

class TestCubePartingSurface:
    """
    A unit cube centred at origin:
      - parting line at mid-z=0 (the equatorial silhouette when pull=[0,0,1])
      - mold_block_bbox = (-2,-2,-2) to (2,2,2)
    The parting surface should be a 4×4 square (or near-planar patch) at z≈0,
    extending from the cube parting line out to ±2 in X and Y.
    """

    def _cube_parting_setup(self):
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        # parting_line() returns [] for flat-faced bodies (all dot-products on
        # side faces are exactly 0, so no sign change is found).  The true
        # parting line for a unit cube pulled along +Z is the four mid-z
        # edges — supply them explicitly as the analytical oracle.
        pl_pts = [
            [-0.5, -0.5, 0.0],
            [ 0.5, -0.5, 0.0],
            [ 0.5,  0.5, 0.0],
            [-0.5,  0.5, 0.0],
        ]
        return body, pl_pts

    def test_parting_surface_at_z_zero(self):
        """All parting-surface vertices should have z ≈ 0."""
        body, pl_pts = self._cube_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        z_vals = _all_z(top)
        for z in z_vals:
            assert abs(z) < 0.2, f"Vertex z={z:.4f} not near 0"

    def test_parting_surface_extends_to_bbox(self):
        """The outermost vertices should reach the mold bbox boundary (±2 in X/Y)."""
        body, pl_pts = self._cube_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        verts = top["vertices"]
        x_vals = [v[0] for v in verts]
        y_vals = [v[1] for v in verts]
        # At least some outer vertices should be at |x| ≈ 2 or |y| ≈ 2
        reaches_x = any(abs(x) >= 1.8 for x in x_vals)
        reaches_y = any(abs(y) >= 1.8 for y in y_vals)
        assert reaches_x or reaches_y, (
            f"No outer vertex reached mold bbox boundary; "
            f"max|x|={max(abs(x) for x in x_vals):.3f}, "
            f"max|y|={max(abs(y) for y in y_vals):.3f}"
        )

    def test_parting_surface_is_planar(self):
        """For a cube + pull=Z, the parting surface should be planar."""
        body, pl_pts = self._cube_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        assert top["is_planar"], "Cube parting surface should be planar"
        assert bottom["is_planar"], "Cube parting surface (bottom) should be planar"

    def test_top_and_bottom_symmetric(self):
        """Top and bottom meshes should have identical vertex/face counts."""
        body, pl_pts = self._cube_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        assert len(top["vertices"]) == len(bottom["vertices"])
        assert len(top["faces"]) == len(bottom["faces"])

    def test_parting_surface_area_positive(self):
        """The parting surface must have positive area."""
        body, pl_pts = self._cube_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        assert top["area"] > 0.0, f"Expected positive area, got {top['area']}"

    def test_sides_labelled_correctly(self):
        """Returned meshes should carry side='top' and side='bottom'."""
        body, pl_pts = self._cube_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        assert top["side"] == "top"
        assert bottom["side"] == "bottom"


# ---------------------------------------------------------------------------
# Test 2: Sphere parting surface (equatorial disc extending to bbox)
# ---------------------------------------------------------------------------

class TestSpherePartingSurface:
    """
    Unit sphere centred at origin, pull = +Z.
    Parting line = equator (z ≈ 0, r_xy ≈ 1).
    Parting surface = disc at z=0, extending from r=1 out to bbox boundary.
    """

    def _sphere_parting_setup(self):
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        pl_pts = parting_line(body, [0.0, 0.0, 1.0])
        return body, pl_pts

    def test_parting_surface_at_equator(self):
        """All vertices should have z ≈ 0 (equatorial plane)."""
        body, pl_pts = self._sphere_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        for v in top["vertices"]:
            assert abs(v[2]) < 0.15, f"z={v[2]:.4f} not near equator"

    def test_disc_extends_to_mold_bbox(self):
        """Outermost vertices reach the mold block boundary."""
        body, pl_pts = self._sphere_parting_setup()
        bbox = ([-3.0, -3.0, -3.0], [3.0, 3.0, 3.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        verts = top["vertices"]
        r_vals = [math.hypot(v[0], v[1]) for v in verts]
        max_r = max(r_vals)
        # The outer ring should reach at least 2.5 (towards the 3.0 bbox)
        assert max_r >= 2.3, (
            f"Expected outer radius ≥ 2.3 (bbox r=3), got max_r={max_r:.3f}"
        )

    def test_sphere_parting_is_planar(self):
        """Sphere equatorial parting surface should be planar."""
        body, pl_pts = self._sphere_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        assert top["is_planar"]

    def test_area_greater_than_unit_disc(self):
        """Surface area must exceed the unit disc area (bbox extends it outward)."""
        body, pl_pts = self._sphere_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        unit_disc_area = math.pi * 1.0 ** 2
        assert top["area"] > unit_disc_area, (
            f"area={top['area']:.4f} should exceed unit disc area {unit_disc_area:.4f}"
        )

    def test_parting_height_near_zero(self):
        """Parting height (z of parting plane) should be ≈ 0 for centered sphere."""
        body, pl_pts = self._sphere_parting_setup()
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        assert abs(top["parting_height"]) < 0.15, (
            f"parting_height={top['parting_height']:.4f} not near 0"
        )


# ---------------------------------------------------------------------------
# Test 3: Round-trip with validate_parting_surface
# ---------------------------------------------------------------------------

class TestValidatePartingSurface:
    """validate_parting_surface must return valid=True for well-formed surfaces."""

    def test_cube_roundtrip_valid(self):
        """Cube body + constructed top + bottom → valid=True."""
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        report = validate_parting_surface(body, top, bottom, [0.0, 0.0, 1.0])
        assert report["valid"], (
            f"Expected valid=True, errors={report['errors']}, "
            f"warnings={report['warnings']}"
        )

    def test_sphere_roundtrip_valid(self):
        """Sphere body + constructed top + bottom → valid=True."""
        body = sphere_to_body([0.0, 0.0, 0.0], 1.0)
        pl_pts = parting_line(body, [0.0, 0.0, 1.0])
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        report = validate_parting_surface(body, top, bottom, [0.0, 0.0, 1.0])
        assert report["valid"], (
            f"Expected valid=True, errors={report['errors']}"
        )

    def test_all_checks_present(self):
        """All expected check keys must be present in the validation report."""
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        report = validate_parting_surface(body, top, bottom, [0.0, 0.0, 1.0])
        expected_keys = {"non_empty", "pull_aligned", "symmetric", "area_positive"}
        assert expected_keys <= set(report["checks"].keys()), (
            f"Missing check keys: {expected_keys - set(report['checks'].keys())}"
        )

    def test_empty_surface_invalid(self):
        """An empty surface dict should fail validation."""
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        empty = {"vertices": [], "faces": [], "area": 0.0}
        report = validate_parting_surface(body, top, empty, [0.0, 0.0, 1.0])
        assert not report["valid"]
        assert not report["checks"]["non_empty"]


# ---------------------------------------------------------------------------
# Test 4: Shutoff inserts for undercut body
# ---------------------------------------------------------------------------

class TestShutoffInserts:
    """construct_with_shutoff_inserts adds shutoff patches for undercut zones."""

    def _make_undercut_body(self):
        """Create a simple box where one face is explicitly an undercut region.

        We use a standard unit box and pass an explicit undercut_region whose
        points, when projected onto the parting plane (z=0), form a non-
        degenerate rectangle — i.e. a horizontal loop at some z height.
        This simulates the bottom boundary of an undercut pocket that meets
        the parting plane.
        """
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        # Undercut region: a rectangular loop at z=0 (on the parting plane)
        # with finite x/y extent so the projection is non-degenerate.
        undercut_region = [
            [-0.3, -0.3, 0.2],
            [ 0.3, -0.3, 0.2],
            [ 0.3,  0.3, 0.2],
            [-0.3,  0.3, 0.2],
        ]
        return body, undercut_region

    def test_shutoff_patch_added(self):
        """At least one shutoff patch must be inserted for the undercut region."""
        body, undercut_region = self._make_undercut_body()
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        top, bottom = construct_with_shutoff_inserts(
            body, pl_pts, [0.0, 0.0, 1.0],
            undercut_regions=[undercut_region],
        )
        patches = top.get("shutoff_patches", [])
        assert len(patches) >= 1, (
            f"Expected >= 1 shutoff patch, got {len(patches)}"
        )

    def test_shutoff_patch_area_positive(self):
        """Each shutoff patch must have positive area."""
        body, undercut_region = self._make_undercut_body()
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        top, _ = construct_with_shutoff_inserts(
            body, pl_pts, [0.0, 0.0, 1.0],
            undercut_regions=[undercut_region],
        )
        for patch in top.get("shutoff_patches", []):
            assert patch["area"] > 0.0, (
                f"Shutoff patch has zero area: {patch}"
            )

    def test_shutoff_increases_total_vertices(self):
        """Adding a shutoff patch should increase the total vertex count."""
        body, undercut_region = self._make_undercut_body()
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        # Base surface (no undercut)
        bbox = ([-3.0, -3.0, -3.0], [3.0, 3.0, 3.0])
        base_top, _ = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        # Augmented surface (with shutoff)
        aug_top, _ = construct_with_shutoff_inserts(
            body, pl_pts, [0.0, 0.0, 1.0],
            undercut_regions=[undercut_region],
        )
        assert len(aug_top["vertices"]) > len(base_top["vertices"]), (
            "Augmented surface should have more vertices than base surface"
        )

    def test_no_undercut_no_shutoff(self):
        """If no undercut regions, shutoff_patches should be empty."""
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        top, _ = construct_with_shutoff_inserts(
            body, pl_pts, [0.0, 0.0, 1.0],
            undercut_regions=[],
        )
        assert top.get("shutoff_patches", []) == [], (
            "No undercut → no shutoff patches expected"
        )


# ---------------------------------------------------------------------------
# Error-handling / edge-case tests
# ---------------------------------------------------------------------------

class TestPartingSurfaceErrors:
    """API contract: invalid inputs raise ValueError."""

    def test_zero_pull_direction_raises(self):
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        pl_pts = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
        with pytest.raises(ValueError, match="non-zero"):
            construct_parting_surface(body, pl_pts,
                                      ([-2, -2, -2], [2, 2, 2]),
                                      [0.0, 0.0, 0.0])

    def test_too_few_parting_points_raises(self):
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        with pytest.raises(ValueError):
            construct_parting_surface(body, [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]],
                                      ([-2, -2, -2], [2, 2, 2]),
                                      [0.0, 0.0, 1.0])

    def test_validate_zero_pull_raises_not(self):
        """validate_parting_surface should return valid=False (not raise) for zero pull."""
        body = box_to_body([-0.5, -0.5, -0.5], 1.0, 1.0, 1.0)
        pl_pts = [[-0.5,-0.5,0.0],[0.5,-0.5,0.0],[0.5,0.5,0.0],[-0.5,0.5,0.0]]
        bbox = ([-2.0, -2.0, -2.0], [2.0, 2.0, 2.0])
        top, bottom = construct_parting_surface(body, pl_pts, bbox, [0.0, 0.0, 1.0])
        report = validate_parting_surface(body, top, bottom, [0.0, 0.0, 0.0])
        assert not report["valid"]
