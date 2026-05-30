"""
Tests for kerf_tess.adaptive_lod — screen-space adaptive tessellation LOD driver.

Analytic oracles:
1. LOD count        — unit sphere → generate_lod_chain yields 4 levels with
                      monotonically *decreasing* triangle counts.
2. Coarsest count   — at pixel_error=16 → coarsest LOD has ≤ 1/4 triangles
                      of finest.
3. Screen-error math— chord_deviation(px=2, d=1000, fov=60°, vp=1080) ≈ 2.14mm
                      (within 1 %).
4. LOD picker       — at d=10 000 mm → picks coarsest LOD;
                      at d=100 mm → picks finest LOD.
"""

from __future__ import annotations

import math
import sys
import os

# Ensure kerf_tess src is importable in all test runner configurations
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import numpy as np


# ── Helpers ────────────────────────────────────────────────────────────────────


def _sphere_body(radius: float = 50.0):
    """Return a sphere Body (or surface-body duck-type) for testing.

    Default radius 50 mm so that chord-deviation tolerances at d=1000 mm
    (2..16 px budget) lie well within the sphere geometry, producing
    meaningfully differentiated triangle counts across all 4 LOD levels.

    For the screen-error formula tests a 1 mm radius is fine because those
    tests only call ``screen_error_to_chord_deviation`` directly.
    """
    # Try the full B-rep path first; fall back to a minimal surface wrapper.
    try:
        sys.path.insert(
            0,
            os.path.join(os.path.dirname(__file__), "..", "..", "kerf-cad-core", "src"),
        )
        from kerf_cad_core.geom.brep_build import sphere_to_body
        return sphere_to_body([0.0, 0.0, 0.0], radius)
    except Exception:
        pass

    # Minimal fallback: surface-only body
    try:
        from kerf_cad_core.geom.brep import SphereSurface
    except ImportError:
        # Inline pure-Python SphereSurface for completely hermetic tests
        class SphereSurface:  # type: ignore[no-redef]
            def __init__(self, center, radius):
                self.center = np.asarray(center, dtype=float)
                self.radius = float(radius)

            def evaluate(self, u: float, v: float) -> np.ndarray:
                cv = math.cos(v)
                return self.center + self.radius * np.array(
                    [cv * math.cos(u), cv * math.sin(u), math.sin(v)]
                )

    srf = SphereSurface(center=np.zeros(3), radius=radius)

    class _SrfBody:
        def __init__(self, surface):
            self._surface = surface
        def evaluate(self, u, v):
            return self._surface.evaluate(u, v)

    return _SrfBody(srf)


# ── Test 1: LOD count and monotonicity ────────────────────────────────────────


def test_lod_chain_count_and_monotonic_triangle_decrease():
    """Unit sphere → 4 LOD levels with monotonically decreasing triangle counts."""
    from kerf_tess.adaptive_lod import generate_lod_chain

    body = _sphere_body()
    levels = generate_lod_chain(
        body,
        target_levels=4,
        pixel_error_budget=[2.0, 4.0, 8.0, 16.0],
        viewing_distance=1000.0,
        fov_y=math.radians(60.0),
        viewport_height_pixels=1080.0,
    )

    # Must produce exactly 4 levels
    assert len(levels) == 4, f"expected 4 levels, got {len(levels)}"

    # Level indices must be 0, 1, 2, 3
    assert [lv.level for lv in levels] == [0, 1, 2, 3]

    # Triangle counts must be strictly decreasing (finest → coarsest)
    tri_counts = [lv.triangle_count for lv in levels]
    for i in range(len(tri_counts) - 1):
        assert tri_counts[i] > tri_counts[i + 1], (
            f"LOD {i} ({tri_counts[i]} tris) must have more than "
            f"LOD {i+1} ({tri_counts[i+1]} tris)"
        )

    # Chord deviation must be monotonically increasing
    chords = [lv.chord_deviation_used for lv in levels]
    for i in range(len(chords) - 1):
        assert chords[i] < chords[i + 1], (
            f"chord_deviation at LOD {i} ({chords[i]:.4f}) must be less than "
            f"LOD {i+1} ({chords[i+1]:.4f})"
        )

    # vertex_count / triangle_count must match mesh attributes
    for lv in levels:
        assert lv.vertex_count == lv.mesh.vertex_count
        assert lv.triangle_count == lv.mesh.triangle_count
        assert lv.vertex_count > 0
        assert lv.triangle_count > 0


# ── Test 2: Coarsest LOD ratio ─────────────────────────────────────────────────


def test_coarsest_lod_has_quarter_or_fewer_triangles_of_finest():
    """Coarsest LOD (pixel_error=16) must have ≤ 1/4 the triangles of finest (pixel_error=2)."""
    from kerf_tess.adaptive_lod import generate_lod_chain

    body = _sphere_body()
    levels = generate_lod_chain(
        body,
        target_levels=4,
        pixel_error_budget=[2.0, 4.0, 8.0, 16.0],
        viewing_distance=1000.0,
        fov_y=math.radians(60.0),
        viewport_height_pixels=1080.0,
    )

    finest = levels[0]
    coarsest = levels[-1]

    ratio = coarsest.triangle_count / finest.triangle_count
    assert ratio <= 0.25, (
        f"Coarsest LOD ({coarsest.triangle_count} tris) must be ≤ 1/4 of "
        f"finest LOD ({finest.triangle_count} tris). Actual ratio: {ratio:.4f}"
    )


# ── Test 3: Screen-error formula ───────────────────────────────────────────────


def test_screen_error_to_chord_deviation_analytic_oracle():
    """chord_deviation(px=2, d=1000, fov=60°, vp=1080) ≈ 2.14 mm (within 1 %)."""
    from kerf_tess.adaptive_lod import screen_error_to_chord_deviation

    # Analytical value from formula:
    #   chord = px * d * 2 * tan(fov/2) / vp
    #         = 2 * 1000 * 2 * tan(30°) / 1080
    #         = 4000 * tan(pi/6) / 1080
    #         = 4000 * (1/sqrt(3)) / 1080
    pixel_error = 2.0
    d = 1000.0
    fov = math.radians(60.0)
    vp = 1080.0

    expected = pixel_error * d * 2.0 * math.tan(fov / 2.0) / vp

    result = screen_error_to_chord_deviation(
        pixel_error=pixel_error,
        viewing_distance=d,
        fov_y=fov,
        viewport_height_pixels=vp,
    )

    # Analytical check: expected ≈ 4000/(1080*sqrt(3)) ≈ 2.1433 mm
    assert abs(expected - result) < 1e-10, (
        f"Function result ({result}) must match analytical formula ({expected})"
    )

    # Value within 1% of the specified 2.14 mm reference
    reference = 2.14
    rel_error = abs(result - reference) / reference
    assert rel_error < 0.01, (
        f"chord_deviation result {result:.4f} mm is more than 1% from "
        f"reference {reference} mm (rel_error={rel_error:.4%})"
    )


def test_screen_error_scales_linearly_with_pixel_error():
    """Doubling pixel_error must double chord_deviation."""
    from kerf_tess.adaptive_lod import screen_error_to_chord_deviation

    c1 = screen_error_to_chord_deviation(1.0, 1000.0, math.radians(60.0), 1080.0)
    c2 = screen_error_to_chord_deviation(2.0, 1000.0, math.radians(60.0), 1080.0)
    assert abs(c2 / c1 - 2.0) < 1e-10, "chord deviation must scale linearly with pixel_error"


def test_screen_error_invalid_inputs():
    """Negative or zero inputs raise ValueError."""
    from kerf_tess.adaptive_lod import screen_error_to_chord_deviation

    with pytest.raises(ValueError):
        screen_error_to_chord_deviation(2.0, -1.0, math.radians(60.0), 1080.0)

    with pytest.raises(ValueError):
        screen_error_to_chord_deviation(2.0, 1000.0, math.radians(60.0), 0.0)

    with pytest.raises(ValueError):
        screen_error_to_chord_deviation(-1.0, 1000.0, math.radians(60.0), 1080.0)


# ── Test 4: LOD picker ─────────────────────────────────────────────────────────


def test_lod_picker_far_distance_returns_coarsest():
    """At d=10 000 mm → pick_lod_for_distance returns the coarsest LOD (level 3).

    Reference distance 1000 mm; at 10 000 mm scale = 0.1, so effective px for
    level 3 (budget=16) is 16 * 0.1 = 1.6 ≤ max_budget (16) → level 3 picked.
    """
    from kerf_tess.adaptive_lod import pick_lod_for_distance

    body = _sphere_body()
    lod = pick_lod_for_distance(
        body,
        distance=10000.0,
        viewport_pixels=1080.0,
        fov_y=math.radians(60.0),
        target_levels=4,
        pixel_error_budget=[2.0, 4.0, 8.0, 16.0],
        reference_distance=1000.0,
    )

    assert lod.level == 3, (
        f"At d=10000mm expected coarsest LOD (level=3), got level={lod.level}"
    )


def test_lod_picker_close_distance_returns_finest():
    """At d=100 mm → pick_lod_for_distance returns the finest LOD (level 0).

    Reference distance 1000 mm; at d=100 mm scale = 10, so effective px for
    level 0 (budget=2) is 2 * 10 = 20 > max_budget (16) → no level qualifies →
    returns finest (level 0 fallback).
    """
    from kerf_tess.adaptive_lod import pick_lod_for_distance

    body = _sphere_body()
    lod = pick_lod_for_distance(
        body,
        distance=100.0,
        viewport_pixels=1080.0,
        fov_y=math.radians(60.0),
        target_levels=4,
        pixel_error_budget=[2.0, 4.0, 8.0, 16.0],
        reference_distance=1000.0,
    )

    assert lod.level == 0, (
        f"At d=100mm expected finest LOD (level=0), got level={lod.level}"
    )


# ── Additional correctness tests ──────────────────────────────────────────────


def test_lod_chain_wrong_budget_length_raises():
    """Mismatched pixel_error_budget length raises ValueError."""
    from kerf_tess.adaptive_lod import generate_lod_chain

    body = _sphere_body()
    with pytest.raises(ValueError, match="pixel_error_budget length"):
        generate_lod_chain(body, target_levels=4, pixel_error_budget=[2.0, 4.0])


def test_lod_level_mesh_vertices_on_sphere_surface():
    """Finest LOD vertices should lie approximately on the sphere surface (r=50 mm)."""
    from kerf_tess.adaptive_lod import generate_lod_chain

    R = 50.0
    body = _sphere_body(radius=R)
    levels = generate_lod_chain(
        body,
        target_levels=2,
        pixel_error_budget=[2.0, 16.0],
        viewing_distance=1000.0,
        fov_y=math.radians(60.0),
        viewport_height_pixels=1080.0,
    )
    finest = levels[0]
    verts = finest.mesh.vertices  # shape (V, 3)

    # Radii should be ≈ R (sphere of radius R, centre at origin)
    radii = np.linalg.norm(verts, axis=1)
    assert np.all(radii > R * 0.5), "Some vertices have radius < 0.5*R (wrong geometry)"
    assert np.allclose(radii, R, atol=R * 0.05), (
        f"Sphere vertices not on sphere surface (R={R}); "
        f"radius range: [{radii.min():.4f}, {radii.max():.4f}]"
    )


def test_triangle_mesh_index_validity():
    """All triangle indices must be within bounds of the vertex array."""
    from kerf_tess.adaptive_lod import generate_lod_chain

    body = _sphere_body()
    levels = generate_lod_chain(
        body,
        target_levels=2,
        pixel_error_budget=[4.0, 16.0],
        viewing_distance=1000.0,
        fov_y=math.radians(60.0),
        viewport_height_pixels=1080.0,
    )
    for lv in levels:
        verts = lv.mesh.vertices
        tris = lv.mesh.triangles
        assert tris.min() >= 0, "Negative triangle index"
        assert tris.max() < len(verts), (
            f"Triangle index {tris.max()} out of range (vertex count={len(verts)})"
        )
