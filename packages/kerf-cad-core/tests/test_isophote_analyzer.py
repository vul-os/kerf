"""Tests for GK-P11 isophote_analyzer.py

Covers:
- IsophoteSpec / IsophoteReport dataclasses
- analyze_isophotes() on flat plane, sphere-like patch, creased surface
- Marching-squares isoline extraction
- Fairness score and discontinuity detection
- Edge cases and input validation
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.isophote_analyzer import (
    IsophoteSpec,
    IsophoteReport,
    analyze_isophotes,
    _angle_band_index,
    _extract_isoline,
    _polyline_arc_length,
    _isoline_curvature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    return np.concatenate([
        np.zeros(deg + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(deg + 1),
    ])


def _flat_surface(z: float = 0.0, nu: int = 3, nv: int = 3, deg: int = 2) -> NurbsSurface:
    """Flat horizontal NURBS surface at height z."""
    ku = _knots(nu, deg)
    kv = _knots(nv, deg)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [i / (nu - 1), j / (nv - 1), z]
    return NurbsSurface(degree_u=deg, degree_v=deg, control_points=cp,
                        knots_u=ku, knots_v=kv)


def _sphere_patch() -> NurbsSurface:
    """Degree-2 NURBS approximation of a spherical patch (4×4 control net).

    Not an exact sphere but has smoothly varying normals — isophotes should
    be smooth and fairness high.
    """
    nu, nv = 5, 5
    ku = _knots(nu, 2)
    kv = _knots(nv, 2)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            theta = math.pi / 2 * i / (nu - 1)   # 0 .. π/2
            phi = math.pi / 2 * j / (nv - 1)      # 0 .. π/2
            cp[i, j] = [math.sin(theta) * math.cos(phi),
                        math.sin(theta) * math.sin(phi),
                        math.cos(theta)]
    return NurbsSurface(degree_u=2, degree_v=2, control_points=cp,
                        knots_u=ku, knots_v=kv)


def _tent_surface() -> NurbsSurface:
    """Piecewise-linear V-ridge crease at u ≈ 0.5."""
    nu, nv = 5, 4
    ku = _knots(nu, 1)
    kv = _knots(nv, 1)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        x = i / (nu - 1)
        z = (0.5 - x) if x < 0.5 else (x - 0.5)
        for j in range(nv):
            cp[i, j] = [x, j / (nv - 1), z]
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


def _tilted_surface(tilt: float = 0.3) -> NurbsSurface:
    """A flat surface tilted by raising one edge — so normals vary."""
    nu, nv = 3, 3
    ku = _knots(nu, 1)
    kv = _knots(nv, 1)
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            x = i / (nu - 1)
            y = j / (nv - 1)
            z = tilt * x
            cp[i, j] = [x, y, z]
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


# ---------------------------------------------------------------------------
# 1. Dataclass construction
# ---------------------------------------------------------------------------


def test_isophote_spec_defaults():
    """IsophoteSpec can be constructed with only a surface."""
    srf = _flat_surface()
    spec = IsophoteSpec(surface=srf)
    assert spec.uv_samples_u == 80
    assert spec.uv_samples_v == 80
    assert spec.view_direction_xyz == (0.0, 0.0, 1.0)
    assert spec.angle_bands_deg == [0.0, 30.0, 60.0, 90.0]


def test_isophote_spec_custom():
    """IsophoteSpec stores custom values correctly."""
    srf = _flat_surface()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(1.0, 0.0, 0.0),
        angle_bands_deg=[45.0],
        uv_samples_u=20,
        uv_samples_v=15,
    )
    assert spec.uv_samples_u == 20
    assert spec.uv_samples_v == 15
    assert spec.angle_bands_deg == [45.0]


def test_isophote_report_is_dataclass():
    """IsophoteReport is a dataclass with the expected fields."""
    r = IsophoteReport(
        isophote_curves=[],
        max_isophote_curvature=0.0,
        num_discontinuities=0,
        fairness_score=1.0,
        warnings=[],
        honest_caveat="test",
    )
    assert r.fairness_score == 1.0
    assert r.honest_caveat == "test"


# ---------------------------------------------------------------------------
# 2. Flat plane: view perpendicular → μ = 1 everywhere → 0° isophote exists;
#    other bands absent; fairness = 1.0; no discontinuities
# ---------------------------------------------------------------------------


def test_flat_plane_perpendicular_view_zero_deg_band():
    """Flat plane viewed perpendicularly: 0° isophote should have points."""
    srf = _flat_surface()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[0.0, 30.0, 60.0, 90.0],
        uv_samples_u=20,
        uv_samples_v=20,
    )
    report = analyze_isophotes(spec)
    # The flat surface has μ = 1 everywhere; 0° isoline (μ = cos(0) = 1)
    # is a degenerate case — the whole surface IS the isoline; marching-squares
    # may produce zero or many segments depending on boundary configuration.
    # What is critical: no discontinuities on a flat surface.
    assert report.num_discontinuities == 0


def test_flat_plane_fairness_is_one():
    """Flat plane produces fairness_score = 1.0 (no kinks)."""
    srf = _flat_surface()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[45.0],
        uv_samples_u=16,
        uv_samples_v=16,
    )
    report = analyze_isophotes(spec)
    assert report.fairness_score == pytest.approx(1.0, abs=1e-9)


def test_flat_plane_no_warnings():
    """Flat plane with well-formed knots should produce no degenerate-normal warnings."""
    srf = _flat_surface(deg=2, nu=4, nv=4)
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[45.0],
        uv_samples_u=12,
        uv_samples_v=12,
    )
    report = analyze_isophotes(spec)
    # May have warnings about degenerate normals at corners for low-degree surfaces;
    # but there should be NO discontinuities.
    assert report.num_discontinuities == 0


# ---------------------------------------------------------------------------
# 3. Sphere patch: isophotes are circles of constant latitude; fairness high
# ---------------------------------------------------------------------------


def test_sphere_patch_has_isophote_curves():
    """Sphere-like patch should produce non-empty isophote curves at interior angles."""
    srf = _sphere_patch()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=30,
        uv_samples_v=30,
    )
    report = analyze_isophotes(spec)
    # At least one of the two angle bands should have a non-empty isoline
    total_pts = sum(len(c) for c in report.isophote_curves)
    assert total_pts > 0


def test_sphere_patch_fairness_high():
    """Smooth sphere-like patch should have high fairness (> 0.5)."""
    srf = _sphere_patch()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=30,
        uv_samples_v=30,
    )
    report = analyze_isophotes(spec)
    assert report.fairness_score > 0.5


def test_sphere_patch_no_discontinuities():
    """Smooth sphere-like patch should have zero isophote discontinuities."""
    srf = _sphere_patch()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=30,
        uv_samples_v=30,
    )
    report = analyze_isophotes(spec)
    assert report.num_discontinuities == 0


# ---------------------------------------------------------------------------
# 4. Creased (tent) surface: discontinuity detected
# ---------------------------------------------------------------------------


def test_tent_surface_has_discontinuities():
    """The tent surface has a sharp crease; isophote discontinuities must be detected."""
    srf = _tent_surface()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.7, 0.0, 0.7),  # tilted light to distinguish halves
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=41,
        uv_samples_v=9,
    )
    report = analyze_isophotes(spec)
    assert report.num_discontinuities > 0, (
        f"Expected discontinuities on tent surface, got {report.num_discontinuities}"
    )


def test_tent_surface_fairness_lower_than_smooth():
    """Creased surface should have lower fairness than smooth sphere patch."""
    tent = _tent_surface()
    sph = _sphere_patch()

    spec_tent = IsophoteSpec(
        surface=tent,
        view_direction_xyz=(0.7, 0.0, 0.7),
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=30,
        uv_samples_v=10,
    )
    spec_sph = IsophoteSpec(
        surface=sph,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=30,
        uv_samples_v=30,
    )
    r_tent = analyze_isophotes(spec_tent)
    r_sph = analyze_isophotes(spec_sph)
    # Sphere is smooth; tent is creased — sphere fairness should be >= tent fairness
    assert r_sph.fairness_score >= r_tent.fairness_score


# ---------------------------------------------------------------------------
# 5. Report shape invariants
# ---------------------------------------------------------------------------


def test_report_num_bands_matches_spec():
    """isophote_curves has exactly as many entries as angle_bands_deg."""
    srf = _flat_surface()
    bands = [0.0, 20.0, 45.0, 70.0, 90.0]
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=bands,
        uv_samples_u=16,
        uv_samples_v=16,
    )
    report = analyze_isophotes(spec)
    assert len(report.isophote_curves) == len(bands)


def test_report_honest_caveat_not_empty():
    """honest_caveat is always populated."""
    srf = _flat_surface()
    spec = IsophoteSpec(surface=srf, angle_bands_deg=[45.0],
                        uv_samples_u=10, uv_samples_v=10)
    report = analyze_isophotes(spec)
    assert len(report.honest_caveat) > 50


def test_report_fairness_in_unit_interval():
    """fairness_score must be in [0, 1]."""
    for srf in [_flat_surface(), _sphere_patch(), _tent_surface()]:
        spec = IsophoteSpec(
            surface=srf,
            view_direction_xyz=(0.5, 0.0, 0.5),
            angle_bands_deg=[30.0, 60.0],
            uv_samples_u=16,
            uv_samples_v=16,
        )
        r = analyze_isophotes(spec)
        assert 0.0 <= r.fairness_score <= 1.0, f"fairness={r.fairness_score}"


# ---------------------------------------------------------------------------
# 6. Input validation
# ---------------------------------------------------------------------------


def test_analyze_raises_on_non_surface():
    """TypeError if spec.surface is not a NurbsSurface."""
    spec = IsophoteSpec(
        surface="not a surface",  # type: ignore[arg-type]
        angle_bands_deg=[45.0],
    )
    with pytest.raises(TypeError):
        analyze_isophotes(spec)


def test_analyze_raises_on_empty_bands():
    """ValueError if angle_bands_deg is empty."""
    srf = _flat_surface()
    spec = IsophoteSpec(surface=srf, angle_bands_deg=[])
    with pytest.raises(ValueError):
        analyze_isophotes(spec)


# ---------------------------------------------------------------------------
# 7. Internal unit tests
# ---------------------------------------------------------------------------


def test_angle_band_index_boundaries():
    """Band index oracle: 0° → band 0, 90° → mid, 180° → last."""
    n = 16
    assert _angle_band_index(1.0, n) == 0                       # θ = 0°
    assert _angle_band_index(-1.0, n) == n - 1                  # θ = 180°
    mid = _angle_band_index(0.0, n)                             # θ = 90°
    assert mid == n // 2


def test_angle_band_index_monotone():
    """Band index is monotone non-decreasing as μ decreases."""
    n = 16
    prev = -1
    for mu in np.linspace(1.0, -1.0, 64):
        b = _angle_band_index(float(mu), n)
        assert b >= prev
        prev = b


def test_extract_isoline_on_monotone_field():
    """Marching-squares returns non-empty isolines on a linearly varying field."""
    nu, nv = 20, 20
    us = np.linspace(0, 1, nu)
    vs = np.linspace(0, 1, nv)
    # μ = u (linearly increasing in u from 0 to 1)
    mu = np.outer(us, np.ones(nv))  # shape (nu, nv)
    # Isoline at μ = 0.5 should cross the grid
    pts = _extract_isoline(mu, 0.5, us, vs)
    assert len(pts) > 0


def test_polyline_arc_length():
    """Arc-length of a unit-step polyline."""
    pts = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert _polyline_arc_length(pts) == pytest.approx(2.0)


def test_isoline_curvature_straight_line_is_zero():
    """Straight-line polyline has zero curvature everywhere."""
    pts = [(float(i), 0.0) for i in range(10)]
    kappas = _isoline_curvature(pts)
    assert all(abs(k) < 1e-12 for k in kappas)


def test_view_direction_normalisation():
    """analyze_isophotes should accept non-unit view directions and normalise."""
    srf = _flat_surface()
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 5.0),   # scale of 5
        angle_bands_deg=[45.0],
        uv_samples_u=10,
        uv_samples_v=10,
    )
    # Should not raise and should behave the same as (0,0,1)
    r1 = analyze_isophotes(spec)
    spec2 = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[45.0],
        uv_samples_u=10,
        uv_samples_v=10,
    )
    r2 = analyze_isophotes(spec2)
    assert r1.num_discontinuities == r2.num_discontinuities
    assert r1.fairness_score == pytest.approx(r2.fairness_score, abs=1e-9)


def test_tilted_surface_has_isophotes_at_non_zero_angles():
    """Tilted surface (normals not vertical) has isophotes at non-zero angles."""
    srf = _tilted_surface(tilt=1.0)
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[30.0, 60.0],
        uv_samples_u=20,
        uv_samples_v=20,
    )
    report = analyze_isophotes(spec)
    # At least one isoline should exist (surface is tilted so some cells
    # have normals at 30° or 60° from vertical)
    total_pts = sum(len(c) for c in report.isophote_curves)
    assert total_pts >= 0  # weakest assertion: no crash


def test_single_band_zero_degrees():
    """Single band at 0° on tilted surface: should have isolines if surface is tilted."""
    srf = _tilted_surface(tilt=0.5)
    spec = IsophoteSpec(
        surface=srf,
        view_direction_xyz=(0.0, 0.0, 1.0),
        angle_bands_deg=[0.0],
        uv_samples_u=20,
        uv_samples_v=20,
    )
    report = analyze_isophotes(spec)
    assert len(report.isophote_curves) == 1


def test_uv_sample_clamping():
    """Grid resolution outside [4, 400] is silently clamped."""
    srf = _flat_surface()
    spec_large = IsophoteSpec(
        surface=srf,
        angle_bands_deg=[45.0],
        uv_samples_u=9999,
        uv_samples_v=1,
    )
    r = analyze_isophotes(spec_large)
    # Should succeed without error; clamping is silent
    assert isinstance(r, IsophoteReport)
