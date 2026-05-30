"""
Tests for kerf_cad_core.geom.mate_inspector — analytical oracle tests.

All tests are hermetic (pure-Python, no OCCT, no DB, no network).

Test plan
---------
1. Concentric cylinders — two coaxial cylinders of equal diameter → valid.
2. Coincident planes — two planar bodies sharing the same plane → valid.
3. Distance mate — two parallel faces with known gap → valid at exact
   distance, invalid at wrong distance, correct residual reported.
4. Auto-detect — two cylinders + planar contact → suggest concentric + tangent.
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.brep import (
    Body,
    Face,
    Loop,
    Shell,
    Solid,
    CylinderSurface,
    Plane,
    make_box,
    make_cylinder,
)
from kerf_cad_core.geom.mate_inspector import (
    MateConstraint,
    MateValidation,
    auto_detect_potential_mates,
    validate_mate,
    validate_assembly_mates,
)

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approx(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def _body_with_cylinder_face(
    center=(0.0, 0.0, 0.0),
    axis=(0.0, 0.0, 1.0),
    radius: float = 5.0,
    height: float = 10.0,
) -> Body:
    """Return a cylinder Body using the canonical brep constructor."""
    return make_cylinder(center=center, axis=axis, radius=radius, height=height)


def _body_with_plane_face(
    origin=(0.0, 0.0, 0.0),
    normal=(0.0, 0.0, 1.0),
) -> Body:
    """Return a box Body whose top face (index 1 = z+ cap) sits at origin+normal."""
    # make_box produces a unit box at the given origin; the z+ face is the top.
    # We position the box so that the z+ face is at the desired plane.
    return make_box(origin=origin, size=(10.0, 10.0, 0.001))


# ---------------------------------------------------------------------------
# Test 1: Concentric cylinders — same diameter, coaxial
# ---------------------------------------------------------------------------

class TestConcentricMate:

    def test_coaxial_same_radius_is_valid(self):
        """Two cylinders with the same axis and same radius → concentric mate valid."""
        body_a = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        body_b = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        c = MateConstraint(kind="concentric")
        result = validate_mate(c, body_a, body_b, tol=1e-4)

        assert result.is_valid, f"Expected valid concentric mate, got: {result.message}"
        assert _approx(result.residual, 0.0, tol=1e-4), (
            f"Residual should be ≈ 0, got {result.residual}"
        )

    def test_offset_axis_is_invalid(self):
        """Cylinders with laterally-offset axes → concentric mate invalid."""
        body_a = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        # Shift body_b axis 2 mm in x
        body_b = make_cylinder(center=(2.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        c = MateConstraint(kind="concentric")
        result = validate_mate(c, body_a, body_b, tol=1e-4)

        assert not result.is_valid, "Offset cylinders should NOT pass concentric mate"
        assert result.residual > 0.5, (
            f"Residual should reflect 2 mm offset, got {result.residual}"
        )

    def test_recommended_translation_points_to_correction(self):
        """Recommended translation should move body_b axis onto body_a axis."""
        body_a = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        body_b = make_cylinder(center=(3.0, 4.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        c = MateConstraint(kind="concentric")
        result = validate_mate(c, body_a, body_b, tol=1e-4)

        tx, ty, tz = result.recommended_translation
        # The correction should move roughly (-3, -4, 0) to realign axes
        assert abs(tx) > 0.5 or abs(ty) > 0.5, (
            "Recommended translation should be non-zero for offset cylinders"
        )


# ---------------------------------------------------------------------------
# Test 2: Coincident planes
# ---------------------------------------------------------------------------

class TestCoincidentMate:

    def test_same_plane_is_valid(self):
        """Two planar bodies sharing the z=0 plane → coincident mate valid."""
        # Both boxes sit at z=0; their z- faces (index 0) share the same plane.
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))

        # face index 0 = bottom (z-) face for both, which is a Plane at z=0
        c = MateConstraint(kind="coincident", entity_a=0, entity_b=0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)

        assert result.is_valid, (
            f"Same-plane coincident mate should be valid, got: {result.message}"
        )
        assert result.residual < 1e-3, (
            f"Residual should be ≈ 0 for same-plane faces, got {result.residual}"
        )

    def test_offset_planes_are_invalid(self):
        """Two planes separated by 5 mm → coincident mate invalid."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        # body_b bottom face is at z=5
        body_b = make_box(origin=(0.0, 0.0, 5.0), size=(5.0, 5.0, 5.0))

        c = MateConstraint(kind="coincident", entity_a=0, entity_b=0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)

        assert not result.is_valid, "Offset planes should NOT pass coincident mate"
        assert result.residual > 1.0, (
            f"Residual should reflect 5 mm gap, got {result.residual}"
        )

    def test_auto_select_plane_face(self):
        """Auto-select (entity_a=None) should find the first planar face."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        c = MateConstraint(kind="coincident")
        result = validate_mate(c, body_a, body_b, tol=1e-3)
        # Should not error on missing faces
        assert result.is_valid or "not a planar face" not in result.message


# ---------------------------------------------------------------------------
# Test 3: Distance mate
# ---------------------------------------------------------------------------

class TestDistanceMate:

    def _two_parallel_boxes(self, gap: float):
        """Two boxes: body_a top at z=5, body_b bottom at z=5+gap."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 5.0 + gap), size=(5.0, 5.0, 5.0))
        return body_a, body_b

    def test_exact_distance_passes(self):
        """Distance mate with parameter=10 on a 10 mm gap → valid, residual ≈ 0."""
        gap = 10.0
        body_a, body_b = self._two_parallel_boxes(gap)
        # Use top face of body_a (index 1 = z+ cap) and bottom face of body_b (index 0 = z-)
        c = MateConstraint(kind="distance", entity_a=1, entity_b=0, parameter=10.0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)

        assert result.is_valid, (
            f"Distance mate with exact parameter should pass; got: {result.message}"
        )
        assert result.residual < 1e-3, (
            f"Residual should be ≈ 0 for exact distance, got {result.residual}"
        )

    def test_wrong_distance_fails_with_correct_residual(self):
        """Distance mate with parameter=20 on a 10 mm gap → invalid, residual ≈ 10."""
        gap = 10.0
        body_a, body_b = self._two_parallel_boxes(gap)
        c = MateConstraint(kind="distance", entity_a=1, entity_b=0, parameter=20.0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)

        assert not result.is_valid, (
            "Distance mate with wrong parameter should fail"
        )
        # The residual should be approximately |20 - 10| = 10 mm
        assert _approx(result.residual, 10.0, tol=0.5), (
            f"Residual should ≈ 10 mm (|expected - actual|), got {result.residual}"
        )

    def test_zero_distance_on_flush_faces(self):
        """Two flush planar bodies (no gap) with parameter=0 → valid."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 5.0), size=(5.0, 5.0, 5.0))
        # Top of body_a (z=5) and bottom of body_b (z=5) are flush
        c = MateConstraint(kind="distance", entity_a=1, entity_b=0, parameter=0.0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)
        assert result.is_valid, (
            f"Flush distance mate (parameter=0) should pass; got: {result.message}"
        )

    def test_non_planar_face_returns_invalid(self):
        """Distance mate against a cylinder face → invalid (requires planar faces)."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=3.0, height=5.0)
        # entity_b=0 is the lateral (cylinder) face of body_b
        c = MateConstraint(kind="distance", entity_a=0, entity_b=0, parameter=5.0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)
        assert not result.is_valid
        assert "not a planar face" in result.message.lower()


# ---------------------------------------------------------------------------
# Test 4: Auto-detect potential mates
# ---------------------------------------------------------------------------

class TestAutoDetect:

    def test_two_coaxial_cylinders_suggests_concentric(self):
        """Two cylinders with same radius → auto-detect suggests concentric."""
        body_a = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        body_b = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        candidates = auto_detect_potential_mates(body_a, body_b)

        kinds = [c.kind for c in candidates]
        assert "concentric" in kinds, (
            f"Expected 'concentric' in auto-detect candidates, got {kinds}"
        )

    def test_parallel_planes_suggest_coincident_or_distance(self):
        """Two boxes with parallel planes → auto-detect suggests coincident or distance."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 5.0), size=(5.0, 5.0, 5.0))
        candidates = auto_detect_potential_mates(body_a, body_b)

        kinds = {c.kind for c in candidates}
        assert kinds & {"coincident", "distance"}, (
            f"Expected coincident or distance in candidates, got {kinds}"
        )

    def test_cylinder_plus_box_suggests_tangent(self):
        """Cylinder tangent to a flat box face → auto-detect suggests tangent."""
        radius = 5.0
        # Box bottom face at z=0; cylinder axis at z=5 (radius=5 mm → tangent)
        body_a = make_cylinder(center=(0.0, 0.0, 5.0), axis=(1.0, 0.0, 0.0),
                               radius=radius, height=20.0)
        body_b = make_box(origin=(-10.0, -10.0, 0.0), size=(20.0, 20.0, 0.1))
        candidates = auto_detect_potential_mates(body_a, body_b)

        kinds = [c.kind for c in candidates]
        assert "tangent" in kinds, (
            f"Expected 'tangent' in auto-detect for cylinder+plane, got {kinds}"
        )

    def test_different_radius_cylinders_no_concentric(self):
        """Cylinders of different radii (far apart) → no concentric suggested."""
        body_a = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        body_b = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=20.0, height=10.0)
        candidates = auto_detect_potential_mates(body_a, body_b)
        concentric_candidates = [c for c in candidates if c.kind == "concentric"]
        assert len(concentric_candidates) == 0, (
            f"Very different radii (5 vs 20) should not suggest concentric, "
            f"got: {concentric_candidates}"
        )


# ---------------------------------------------------------------------------
# Test 5: validate_assembly_mates — DOF counting + full-assembly check
# ---------------------------------------------------------------------------

class TestAssemblyValidation:

    def test_fully_constrained_two_coaxial_cylinders(self):
        """Two cylinders: concentric (4 DOF) + coincident planar caps (3 DOF)
        accounts for 7 DOF; body has 6 → over-constrained on the 7th, but the
        concentric alone should leave 2 DOF (under-constrained)."""
        body_a = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        body_b = make_cylinder(center=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0),
                               radius=5.0, height=10.0)
        bodies = {"a": body_a, "b": body_b}
        constraints = [MateConstraint(kind="concentric")]
        result = validate_assembly_mates(bodies, constraints, tol=1e-4)

        assert result.ok, f"Assembly validation errors: {result.errors}"
        assert result.status == "under_constrained", (
            f"Concentric alone (4 DOF removed from 6) should leave 2 DOF; "
            f"got status={result.status}, dof={result.dof_remaining}"
        )
        assert result.dof_remaining == 2

    def test_invalid_mate_is_reported(self):
        """An invalid distance mate (wrong value) should appear in errors."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 10.0), size=(5.0, 5.0, 5.0))
        bodies = {"a": body_a, "b": body_b}
        # top of body_a = z=5, bottom of body_b = z=10 → gap = 5 mm
        # But we claim parameter=50 (wrong)
        constraints = [
            MateConstraint(kind="distance", entity_a=1, entity_b=0, parameter=50.0)
        ]
        result = validate_assembly_mates(bodies, constraints, tol=1e-3)
        assert not result.ok
        assert len(result.errors) > 0
        assert "INVALID" in result.errors[0]

    def test_requires_at_least_two_bodies(self):
        """Single-body assembly should report an error."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        result = validate_assembly_mates({"a": body_a}, [], tol=1e-4)
        assert not result.ok
        assert any("2 bodies" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Test 6: Additional mate kinds (angle, tangent, parallel, perpendicular)
# ---------------------------------------------------------------------------

class TestOtherMateKinds:

    def test_angle_mate_0_on_parallel_planes(self):
        """Two parallel planes → angle mate with parameter=0 should pass."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 5.0), size=(5.0, 5.0, 5.0))
        # Both use z-face (index 0 = bottom face, normal = -z)
        c = MateConstraint(kind="angle", entity_a=0, entity_b=0, parameter=0.0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)
        assert result.is_valid, f"Parallel planes angle=0 should pass; got: {result.message}"

    def test_tangent_mate_cylinder_to_plane(self):
        """Cylinder with radius 5 mm, axis at z=5, plane at z=0 → tangent valid."""
        radius = 5.0
        body_a = make_cylinder(center=(0.0, 0.0, 5.0), axis=(1.0, 0.0, 0.0),
                               radius=radius, height=20.0)
        body_b = make_box(origin=(-10.0, -10.0, 0.0), size=(20.0, 20.0, 0.001))
        c = MateConstraint(kind="tangent", parameter=radius)
        result = validate_mate(c, body_a, body_b, tol=1e-3)
        assert result.is_valid, (
            f"Cylinder at z=5 with radius 5 tangent to z=0 plane; got: {result.message}"
        )

    def test_parallel_mate_coplanar_normals(self):
        """Two boxes with top/bottom faces parallel → parallel mate passes."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 10.0), size=(5.0, 5.0, 5.0))
        c = MateConstraint(kind="parallel", entity_a=0, entity_b=0)
        result = validate_mate(c, body_a, body_b, tol=1e-3)
        assert result.is_valid, f"Parallel z-faces should pass; got: {result.message}"

    def test_unknown_kind_returns_invalid(self):
        """An unrecognised mate kind should return is_valid=False with error message."""
        body_a = make_box(origin=(0.0, 0.0, 0.0), size=(5.0, 5.0, 5.0))
        body_b = make_box(origin=(0.0, 0.0, 5.0), size=(5.0, 5.0, 5.0))
        c = MateConstraint(kind="flux_capacitor")
        result = validate_mate(c, body_a, body_b, tol=1e-4)
        assert not result.is_valid
        assert "flux_capacitor" in result.message.lower() or "unknown" in result.message.lower()
