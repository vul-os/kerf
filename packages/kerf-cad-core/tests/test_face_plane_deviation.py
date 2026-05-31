"""Tests for face_plane_deviation.py — BREP-FACE-PLANE-DEVIATION.

Coverage
--------
 1. Truly planar grid — max_dev ≈ 0 (within floating-point eps)
 2. Tilted plane — normal direction recovered correctly
 3. Sphere cap — deviation > tolerance, classified "curved" or "highly-curved"
 4. Fewer than 3 points — ValueError
 5. All collinear points — ValueError
 6. classification thresholds: exact boundary values
 7. is_planar True/False contract
 8. PlaneFit plane equation consistency (n·origin = d)
 9. RMS ≤ max_dev always holds
10. Custom tolerance_mm respected
11. Large planar set (100 points) still planar
12. Tilted 45° plane — normal ≈ (0, -1/√2, 1/√2)
13. Re-export from geom.__init__
14. near-planar classification
15. highly-curved classification
16. Normal is unit length
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.face_plane_deviation import (
    FaceSamplePoint,
    FacePlaneDeviationReport,
    PlaneFit,
    compute_face_plane_deviation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pt(x, y, z) -> FaceSamplePoint:
    return FaceSamplePoint(x_mm=float(x), y_mm=float(y), z_mm=float(z))


def _grid_z(w: float, h: float, nw: int = 5, nh: int = 5, z: float = 0.0):
    """Regular grid on the XY plane at height z."""
    pts = []
    for i in range(nw):
        for j in range(nh):
            pts.append(_pt(i * w / (nw - 1), j * h / (nh - 1), z))
    return pts


def _sphere_cap_points(radius: float, n: int = 6) -> list:
    """Sample n×n grid on a sphere octant (u in [0,π/2], v in [0,π/2])."""
    pts = []
    for i in range(n):
        for j in range(n):
            u = (math.pi / 2) * i / (n - 1)
            v = (math.pi / 2) * j / (n - 1)
            x = radius * math.sin(u) * math.cos(v)
            y = radius * math.sin(u) * math.sin(v)
            z = radius * math.cos(u)
            pts.append(_pt(x, y, z))
    return pts


# ---------------------------------------------------------------------------
# Test 1: truly planar grid — max_dev = 0 (< 1e-12)
# ---------------------------------------------------------------------------

def test_truly_planar_grid_max_dev_zero():
    pts = _grid_z(10.0, 10.0, 6, 6, z=0.0)
    report = compute_face_plane_deviation(pts, tolerance_mm=0.01)
    assert report.max_deviation_mm < 1e-10
    assert report.is_planar is True
    assert report.classification == "planar"


# ---------------------------------------------------------------------------
# Test 2: tilted plane — normal recovered to within 1e-6
# ---------------------------------------------------------------------------

def test_tilted_plane_normal_correct():
    """Plane z=2: all sample points have z=2; normal should be (0,0,±1)."""
    pts = _grid_z(5.0, 5.0, 5, 5, z=2.0)
    report = compute_face_plane_deviation(pts, tolerance_mm=0.01)
    nx, ny, nz = report.plane.normal_xyz
    assert abs(abs(nz) - 1.0) < 1e-8, f"Expected |nz|≈1, got {nz}"
    assert abs(nx) < 1e-8
    assert abs(ny) < 1e-8


# ---------------------------------------------------------------------------
# Test 3: sphere cap — deviation > tolerance, classified curved
# ---------------------------------------------------------------------------

def test_sphere_cap_classified_curved():
    r = 100.0
    pts = _sphere_cap_points(r, n=6)
    report = compute_face_plane_deviation(pts, tolerance_mm=0.01)
    assert not report.is_planar
    assert report.classification in ("curved", "highly-curved")
    assert report.max_deviation_mm > 0.01


# ---------------------------------------------------------------------------
# Test 4: fewer than 3 points raises ValueError
# ---------------------------------------------------------------------------

def test_fewer_than_3_points_raises():
    with pytest.raises(ValueError, match="at least 3"):
        compute_face_plane_deviation([_pt(0, 0, 0), _pt(1, 0, 0)])


def test_one_point_raises():
    with pytest.raises(ValueError, match="at least 3"):
        compute_face_plane_deviation([_pt(0, 0, 0)])


def test_empty_raises():
    with pytest.raises(ValueError, match="at least 3"):
        compute_face_plane_deviation([])


# ---------------------------------------------------------------------------
# Test 5: all collinear points raises ValueError
# ---------------------------------------------------------------------------

def test_collinear_points_raises():
    pts = [_pt(i, 0, 0) for i in range(10)]
    with pytest.raises(ValueError, match="collinear"):
        compute_face_plane_deviation(pts)


# ---------------------------------------------------------------------------
# Test 6: classification thresholds — exact boundary check
# ---------------------------------------------------------------------------

def test_classification_near_planar():
    """Points on a plane with one point lifted by 5×tolerance → near-planar."""
    tol = 0.01
    pts = _grid_z(1.0, 1.0, 4, 4, z=0.0)
    # Lift the last point by 5×tol (inside (tol, 10×tol) window)
    pts[-1] = _pt(pts[-1].x_mm, pts[-1].y_mm, 5.0 * tol)
    report = compute_face_plane_deviation(pts, tolerance_mm=tol)
    assert report.classification == "near-planar"
    assert not report.is_planar


def test_classification_curved():
    """Lift one point by 50×tolerance → curved."""
    tol = 0.01
    pts = _grid_z(1.0, 1.0, 4, 4, z=0.0)
    pts[-1] = _pt(pts[-1].x_mm, pts[-1].y_mm, 50.0 * tol)
    report = compute_face_plane_deviation(pts, tolerance_mm=tol)
    assert report.classification == "curved"


def test_classification_highly_curved():
    """Lift multiple points to simulate a highly-curved surface.

    On a sphere cap of radius 100 mm with tolerance 0.01 mm the max deviation
    from the best-fit plane easily exceeds 100×tol (= 1 mm).
    """
    tol = 0.01
    pts = _sphere_cap_points(radius=100.0, n=8)
    report = compute_face_plane_deviation(pts, tolerance_mm=tol)
    assert report.classification == "highly-curved", (
        f"Expected highly-curved, got {report.classification} "
        f"(max_dev={report.max_deviation_mm:.4f} vs 100*tol={100*tol})"
    )


# ---------------------------------------------------------------------------
# Test 7: is_planar boolean contract
# ---------------------------------------------------------------------------

def test_is_planar_true_for_flat_grid():
    pts = _grid_z(10.0, 10.0, 5, 5)
    r = compute_face_plane_deviation(pts, tolerance_mm=1e-3)
    assert r.is_planar is True


def test_is_planar_false_for_sphere_cap():
    pts = _sphere_cap_points(50.0, n=5)
    r = compute_face_plane_deviation(pts, tolerance_mm=0.01)
    assert r.is_planar is False


# ---------------------------------------------------------------------------
# Test 8: plane equation consistency — n·origin == d
# ---------------------------------------------------------------------------

def test_plane_equation_consistency():
    pts = _grid_z(3.0, 3.0, 4, 4, z=5.0)
    r = compute_face_plane_deviation(pts)
    n = r.plane.normal_xyz
    o = r.plane.origin_xyz_mm
    computed_d = n[0] * o[0] + n[1] * o[1] + n[2] * o[2]
    assert abs(computed_d - r.plane.d) < 1e-10


# ---------------------------------------------------------------------------
# Test 9: RMS ≤ max_dev always
# ---------------------------------------------------------------------------

def test_rms_leq_max_dev():
    pts = _sphere_cap_points(20.0, n=5)
    r = compute_face_plane_deviation(pts, tolerance_mm=0.01)
    assert r.rms_deviation_mm <= r.max_deviation_mm + 1e-14


# ---------------------------------------------------------------------------
# Test 10: custom tolerance_mm respected
# ---------------------------------------------------------------------------

def test_custom_tolerance_changes_classification():
    """Same points: tight tol→near-planar, loose tol→planar."""
    tol_base = 0.01
    pts = _grid_z(1.0, 1.0, 4, 4, z=0.0)
    pts[-1] = _pt(pts[-1].x_mm, pts[-1].y_mm, 5.0 * tol_base)
    r_tight = compute_face_plane_deviation(pts, tolerance_mm=tol_base)
    r_loose = compute_face_plane_deviation(pts, tolerance_mm=1.0)
    assert r_tight.classification == "near-planar"
    assert r_loose.is_planar is True


# ---------------------------------------------------------------------------
# Test 11: large planar set (100 points) still classified planar
# ---------------------------------------------------------------------------

def test_large_planar_set():
    pts = _grid_z(100.0, 100.0, 10, 10, z=0.0)
    r = compute_face_plane_deviation(pts, tolerance_mm=1e-6)
    assert r.max_deviation_mm < 1e-9
    assert r.is_planar is True
    assert r.num_samples == 100


# ---------------------------------------------------------------------------
# Test 12: 45° tilted plane — normal ≈ (0, -sin(45°), cos(45°))
# ---------------------------------------------------------------------------

def test_45_degree_tilted_plane():
    """Points on plane y + z = c → normal ≈ (0, 1/√2, 1/√2)."""
    sqrt2 = math.sqrt(2.0)
    pts = []
    for i in range(5):
        for j in range(5):
            x = float(i)
            y = float(j)
            # plane: y + z = 3 → z = 3 - y
            z = 3.0 - y
            pts.append(_pt(x, y, z))
    r = compute_face_plane_deviation(pts, tolerance_mm=0.001)
    assert r.max_deviation_mm < 1e-9
    nx, ny, nz = r.plane.normal_xyz
    # Normal should be ±(0, 1/√2, 1/√2)
    assert abs(nx) < 1e-8
    assert abs(abs(ny) - 1.0 / sqrt2) < 1e-6
    assert abs(abs(nz) - 1.0 / sqrt2) < 1e-6
    assert abs(abs(ny) - abs(nz)) < 1e-10  # symmetric in y/z


# ---------------------------------------------------------------------------
# Test 13: re-export from geom.__init__
# ---------------------------------------------------------------------------

def test_reexport_from_geom_init():
    from kerf_cad_core.geom import (
        FaceSamplePoint as FSP,
        PlaneFit as PF,
        FacePlaneDeviationReport as FPDR,
        compute_face_plane_deviation as cfpd,
    )
    assert FSP is FaceSamplePoint
    assert PF is PlaneFit
    assert FPDR is FacePlaneDeviationReport
    assert cfpd is compute_face_plane_deviation


# ---------------------------------------------------------------------------
# Test 14: near-planar gives is_planar=False but classification near-planar
# ---------------------------------------------------------------------------

def test_near_planar_is_not_planar():
    tol = 0.01
    pts = _grid_z(1.0, 1.0, 4, 4, z=0.0)
    pts[-1] = _pt(pts[-1].x_mm, pts[-1].y_mm, 5.0 * tol)
    r = compute_face_plane_deviation(pts, tolerance_mm=tol)
    assert r.is_planar is False
    assert r.classification == "near-planar"


# ---------------------------------------------------------------------------
# Test 15: honest_caveat is non-empty string
# ---------------------------------------------------------------------------

def test_honest_caveat_non_empty():
    pts = _grid_z(1.0, 1.0, 3, 3)
    r = compute_face_plane_deviation(pts)
    assert isinstance(r.honest_caveat, str)
    assert len(r.honest_caveat) > 20


# ---------------------------------------------------------------------------
# Test 16: normal is unit length
# ---------------------------------------------------------------------------

def test_normal_is_unit_length():
    pts = _sphere_cap_points(10.0, n=5)
    r = compute_face_plane_deviation(pts)
    nx, ny, nz = r.plane.normal_xyz
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    assert abs(mag - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Test 17: num_samples field correct
# ---------------------------------------------------------------------------

def test_num_samples_field():
    pts = _grid_z(1.0, 1.0, 4, 5)  # 20 points
    r = compute_face_plane_deviation(pts)
    assert r.num_samples == 20


# ---------------------------------------------------------------------------
# Test 18: minimum valid input — exactly 3 non-collinear points
# ---------------------------------------------------------------------------

def test_three_noncollinear_points():
    pts = [_pt(0, 0, 0), _pt(1, 0, 0), _pt(0, 1, 0)]
    r = compute_face_plane_deviation(pts, tolerance_mm=0.01)
    assert r.max_deviation_mm < 1e-10
    assert r.is_planar is True
