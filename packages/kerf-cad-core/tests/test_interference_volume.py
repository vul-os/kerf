"""Tests for GK-P-IV: Interference volume metric.

Analytic oracles:
  1. Identical boxes: 1×1×1 at (0,0,0) — V_int = 1.0  (within MC error).
  2. Half-overlapping boxes: 1×1×1 at (0,0,0) and (0.5,0,0) — V_int = 0.5 (±5%).
  3. No overlap: boxes at (0,0,0) and (5,0,0) — V_int = 0.
  4. Sphere-sphere: unit spheres at (0,0,0) and (1.5,0,0) — spherical lens formula.

All tests use the 'boolean' method as the primary exact oracle. MC tests check
convergence vs. the analytic result.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.brep_build import box_to_body, sphere_to_body
from kerf_cad_core.geom.interference_volume import (
    InterferenceVolume,
    compute_interference_volume,
    interference_severity_score,
    pairwise_interference_assembly,
)


# ---------------------------------------------------------------------------
# Analytic oracle: spherical lens (intersection of two equal unit spheres
# with centres d apart, d < 2).
# ---------------------------------------------------------------------------

def _spherical_lens_volume(r: float, d: float) -> float:
    """Volume of intersection of two spheres of radius r with centres d apart.

    Formula (Cazals-Loriot; also Beyer 1987):
        V = (π/12) × (2r - d)² × (d² + 4rd)  / d    [for 0 < d < 2r]

    Equivalently:
        h = r - d/2   (half the chord height for one cap)
        V = 2 × (π h² / 3) × (3r - h)         [two equal spherical caps]
    """
    if d >= 2 * r:
        return 0.0
    h = r - d / 2.0
    return 2.0 * (math.pi * h ** 2 / 3.0) * (3.0 * r - h)


# ---------------------------------------------------------------------------
# Test 1: Identical 1×1×1 boxes — V_int = 1.0
# ---------------------------------------------------------------------------

class TestIdenticalBoxes:
    """Two identical unit boxes at the same position → full overlap, V = 1.0."""

    def test_boolean_exact(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        result = compute_interference_volume(a, b, method="boolean")
        assert isinstance(result, InterferenceVolume)
        assert math.isclose(result.volume, 1.0, rel_tol=1e-5), (
            f"Expected V=1.0, got {result.volume}"
        )
        assert result.method == "boolean"
        assert result.std_error == 0.0

    def test_monte_carlo_within_error(self):
        """MC estimate of identical boxes must be within 10% of 1.0."""
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        rng = np.random.default_rng(0)
        result = compute_interference_volume(a, b, method="monte_carlo", n_samples=20000, rng=rng)
        assert abs(result.volume - 1.0) <= 0.1, (
            f"MC estimate {result.volume:.4f} is >10% from 1.0"
        )
        assert result.std_error >= 0.0

    def test_severity_is_one(self):
        """Full overlap → severity ≈ 1.0."""
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        result = compute_interference_volume(a, b, method="boolean")
        # Both bodies have volume 1.0; severity = 1.0/1.0 = 1.0
        assert math.isclose(result.interference_severity, 1.0, rel_tol=1e-4), (
            f"Expected severity=1.0, got {result.interference_severity}"
        )


# ---------------------------------------------------------------------------
# Test 2: Half-overlapping boxes — V_int = 0.5
# ---------------------------------------------------------------------------

class TestHalfOverlappingBoxes:
    """Unit boxes at (0,0,0) and (0.5,0,0) → overlap = 0.5×1×1 = 0.5."""

    def test_boolean_exact(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        result = compute_interference_volume(a, b, method="boolean")
        assert math.isclose(result.volume, 0.5, rel_tol=1e-5), (
            f"Expected V=0.5, got {result.volume}"
        )

    def test_monte_carlo_within_5pct(self):
        """MC estimate must land within 5% of the analytic value 0.5."""
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        rng = np.random.default_rng(1)
        result = compute_interference_volume(a, b, method="monte_carlo", n_samples=20000, rng=rng)
        rel_err = abs(result.volume - 0.5) / 0.5
        assert rel_err <= 0.05, (
            f"MC relative error {rel_err:.3f} > 5% (volume={result.volume:.4f})"
        )

    def test_severity_score(self):
        """Severity should be ≈0.5 (0.5 / min(1.0, 1.0) = 0.5)."""
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        result = compute_interference_volume(a, b, method="boolean")
        assert math.isclose(result.interference_severity, 0.5, rel_tol=1e-4), (
            f"Expected severity=0.5, got {result.interference_severity}"
        )


# ---------------------------------------------------------------------------
# Test 3: No overlap — V_int = 0.0
# ---------------------------------------------------------------------------

class TestNoOverlap:
    """Boxes separated by a gap → zero intersection volume."""

    def test_boolean_zero(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(5, 0, 0), dx=1, dy=1, dz=1)
        result = compute_interference_volume(a, b, method="boolean")
        assert result.volume == 0.0
        assert result.interference_severity == 0.0

    def test_monte_carlo_near_zero(self):
        """MC estimate on far-separated boxes should give ~0 (< 0.01 tolerance)."""
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(5, 0, 0), dx=1, dy=1, dz=1)
        rng = np.random.default_rng(2)
        result = compute_interference_volume(a, b, method="monte_carlo", n_samples=10000, rng=rng)
        assert result.volume < 0.01, (
            f"Expected ~0 volume, got {result.volume}"
        )

    def test_severity_zero(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(5, 0, 0), dx=1, dy=1, dz=1)
        score = interference_severity_score(a, b, method="boolean")
        assert score["score"] == 0.0
        assert not score["interferes"]


# ---------------------------------------------------------------------------
# Test 4: Sphere-sphere overlap — analytic spherical lens oracle (±10%)
# ---------------------------------------------------------------------------

class TestSphereSphereOverlap:
    """Two unit spheres with centres 1.5 apart — known analytical volume.

    Notes
    -----
    The pure-Python ``body_intersection`` (GK-18) cannot clip curved SphereSurface
    faces into lens geometry — it returns both full sphere faces, giving the sum of
    both sphere volumes (~8.38) rather than the lens (~0.36).  This is a known
    limitation documented in the ROADMAP ("General solid boolean: NURBS-faced /
    non-axis-aligned solids → not started").  The ``'monte_carlo'`` method handles
    curved bodies correctly via per-face SDF evaluation.
    """

    def test_monte_carlo_within_10pct(self):
        """MC estimate must be within 10% of the analytic spherical lens volume.

        Oracle: Cazals-Loriot 2008 / standard spherical cap formula.
        Two unit spheres, centres 1.5 apart → lens volume ≈ 0.3600.
        """
        r = 1.0
        d = 1.5
        expected = _spherical_lens_volume(r, d)

        a = sphere_to_body(centre=(0, 0, 0), radius=r)
        b = sphere_to_body(centre=(d, 0, 0), radius=r)

        rng = np.random.default_rng(3)
        result = compute_interference_volume(
            a, b, method="monte_carlo", n_samples=50000, rng=rng
        )
        assert result.interferes if hasattr(result, "interferes") else result.volume > 0
        rel_err = abs(result.volume - expected) / expected
        assert rel_err <= 0.10, (
            f"MC sphere overlap: got {result.volume:.5f}, "
            f"expected {expected:.5f}, rel_err={rel_err:.3f}"
        )

    def test_analytic_oracle_value(self):
        """Verify the oracle itself: r=1, d=1.5 → known lens volume ≈ 0.3600."""
        expected = _spherical_lens_volume(1.0, 1.5)
        # h = r - d/2 = 1.0 - 0.75 = 0.25
        # V = 2 × (π h² / 3) × (3r - h) = 2 × (π × 0.0625 / 3) × 2.75
        h = 1.0 - 1.5 / 2.0  # = 0.25
        cap = math.pi * h ** 2 * (3.0 * 1.0 - h) / 3.0
        analytic = 2.0 * cap
        assert math.isclose(expected, analytic, rel_tol=1e-10)
        # Sanity: value should be around 0.36
        assert 0.30 < expected < 0.45

    def test_sphere_no_overlap(self):
        """Spheres at (0,0,0) and (5,0,0) with r=1 → no intersection (d=5 > 2r=2)."""
        a = sphere_to_body(centre=(0, 0, 0), radius=1.0)
        b = sphere_to_body(centre=(5, 0, 0), radius=1.0)
        result = compute_interference_volume(a, b, method="monte_carlo", n_samples=5000)
        assert result.volume < 0.01, (
            f"Expected ~0 sphere intersection, got {result.volume:.5f}"
        )

    def test_sphere_severity_is_positive(self):
        """Overlapping spheres must give positive severity score."""
        r = 1.0
        d = 1.5
        a = sphere_to_body(centre=(0, 0, 0), radius=r)
        b = sphere_to_body(centre=(d, 0, 0), radius=r)
        rng = np.random.default_rng(7)
        result = compute_interference_volume(a, b, method="monte_carlo", n_samples=10000, rng=rng)
        assert result.interference_severity > 0.0, (
            f"Expected positive severity, got {result.interference_severity}"
        )


# ---------------------------------------------------------------------------
# Test 5: interference_severity_score API contract
# ---------------------------------------------------------------------------

class TestSeverityScoreContract:
    """Verify the interference_severity_score dict contract."""

    def test_keys_present(self):
        a = box_to_body(corner=(0, 0, 0), dx=2, dy=2, dz=2)
        b = box_to_body(corner=(1, 1, 1), dx=2, dy=2, dz=2)
        score = interference_severity_score(a, b, method="boolean")
        assert {"score", "volume", "volume_a", "volume_b",
                "min_body_volume", "method", "interferes"}.issubset(score.keys())

    def test_acceptable_key_present_when_threshold_given(self):
        a = box_to_body(corner=(0, 0, 0), dx=2, dy=2, dz=2)
        b = box_to_body(corner=(1, 1, 1), dx=2, dy=2, dz=2)
        score = interference_severity_score(
            a, b, method="boolean", max_acceptable_volume=0.5
        )
        assert "acceptable" in score

    def test_not_acceptable_above_threshold(self):
        # Overlap = 1.0, threshold = 0.5
        a = box_to_body(corner=(0, 0, 0), dx=2, dy=2, dz=2)
        b = box_to_body(corner=(1, 1, 1), dx=2, dy=2, dz=2)
        score = interference_severity_score(
            a, b, method="boolean", max_acceptable_volume=0.5
        )
        # overlap is 1.0 unit³ > 0.5 → not acceptable
        assert not score["acceptable"]

    def test_acceptable_below_threshold(self):
        a = box_to_body(corner=(0, 0, 0), dx=2, dy=2, dz=2)
        b = box_to_body(corner=(1, 1, 1), dx=2, dy=2, dz=2)
        score = interference_severity_score(
            a, b, method="boolean", max_acceptable_volume=2.0
        )
        assert score["acceptable"]


# ---------------------------------------------------------------------------
# Test 6: pairwise_interference_assembly
# ---------------------------------------------------------------------------

class TestPairwiseAssemblyMatrix:
    """Verify the N×N pairwise interference matrix."""

    def test_shape_3x3(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        c = box_to_body(corner=(10, 0, 0), dx=1, dy=1, dz=1)
        mat = pairwise_interference_assembly([a, b, c], method="boolean")
        assert mat.shape == (3, 3)

    def test_diagonal_zero(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        mat = pairwise_interference_assembly([a, b], method="boolean")
        assert mat[0, 0] == 0.0
        assert mat[1, 1] == 0.0

    def test_symmetric(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        c = box_to_body(corner=(10, 0, 0), dx=1, dy=1, dz=1)
        mat = pairwise_interference_assembly([a, b, c], method="boolean")
        np.testing.assert_array_equal(mat, mat.T)

    def test_disjoint_pair_is_zero(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        c = box_to_body(corner=(10, 0, 0), dx=1, dy=1, dz=1)
        mat = pairwise_interference_assembly([a, b, c], method="boolean")
        # a-c and b-c should be zero
        assert mat[0, 2] == 0.0
        assert mat[1, 2] == 0.0

    def test_overlapping_pair_nonzero(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0.5, 0, 0), dx=1, dy=1, dz=1)
        mat = pairwise_interference_assembly([a, b], method="boolean")
        assert mat[0, 1] > 0.0


# ---------------------------------------------------------------------------
# Test 7: invalid method raises ValueError
# ---------------------------------------------------------------------------

class TestInvalidMethod:
    def test_bad_method_raises(self):
        a = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        b = box_to_body(corner=(0, 0, 0), dx=1, dy=1, dz=1)
        with pytest.raises(ValueError, match="Unknown method"):
            compute_interference_volume(a, b, method="spectral")
