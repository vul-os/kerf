"""Tests for BREP-EDGE-CONVEXITY sampled-normals API.

Covers EdgeSample / SampledEdgeConvexityReport / classify_edge_convexity
(Mantyla 1988 §5; Hoffmann 1989 §5.3).

Oracle geometry
---------------
All tests below use right-angle or known-angle wedge geometries so oracle
dihedral angles are computable analytically.

Convention used here
--------------------
* n_a, n_b are *outward* face normals (pointing away from the solid material).
* edge_tangent is the unit tangent along the edge (arbitrary direction, but
  consistent between normals).
* sign = (n_a × n_b) · edge_tangent:
    > 0 → convex (exterior cube corner, dihedral ≈ 90°)
    < 0 → concave (interior L-bracket pocket, dihedral ≈ 90° but re-entrant)
    ≈ 0 → smooth / tangent (coplanar faces or G1 junction)
"""

from __future__ import annotations

import math
from typing import List

import pytest

from kerf_cad_core.geom.edge_convexity import (
    EdgeSample,
    SampledEdgeConvexityReport,
    classify_edge_convexity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample(
    point: tuple,
    na: tuple,
    nb: tuple,
    et: tuple,
) -> EdgeSample:
    return EdgeSample(
        point_xyz_mm=point,
        face_a_normal=na,
        face_b_normal=nb,
        edge_tangent=et,
    )


def _cube_corner_sample(along_x: float = 0.5) -> EdgeSample:
    """One sample at a convex 90° cube exterior edge.

    Edge runs along +X (front-top edge of a unit cube at y=1, z=1).
    Face A (top face): outward normal = (0, 0, 1).
    Face B (front face): outward normal = (0, 1, 0).
    Edge tangent: (1, 0, 0).
    cross(n_a, n_b) = (0,0,1) × (0,1,0) = (-1, 0, 0) ... wait:
        cross((0,0,1), (0,1,0)) = (0*0−1*1, 1*0−0*0, 0*1−0*0) = (−1, 0, 0)
    dot(cross, et=(1,0,0)) = −1 → concave with this tangent direction!
    Flip tangent to (−1, 0, 0): dot = 1 → convex ✓
    """
    return _sample(
        point=(along_x, 1.0, 1.0),
        na=(0.0, 0.0, 1.0),   # top face outward normal
        nb=(0.0, 1.0, 0.0),   # front face outward normal
        et=(-1.0, 0.0, 0.0),  # edge tangent chosen so cross · tangent > 0 → convex
    )


def _l_bracket_sample(along_x: float = 0.5) -> EdgeSample:
    """One sample at a concave 90° interior L-bracket pocket edge.

    The interior pocket edge of an L-bracket: the two faces point *into* the
    notch.  We simulate this by using inward-looking normals in a re-entrant
    geometry.

    Face A: inner vertical face of notch, outward normal = (0, −1, 0)
    Face B: inner floor of notch, outward normal = (0, 0, 1)  (pointing up)
    Edge tangent: (1, 0, 0).

    cross((0,−1,0),(0,0,1)) = (−1*1−0*0, 0*0−0*1, 0*0−(−1)*0)
                             = (−1*1, 0, 0) = (−1, 0, 0)
    dot with (1,0,0) = −1 → concave ✓
    """
    return _sample(
        point=(along_x, 0.0, 0.0),
        na=(0.0, -1.0, 0.0),
        nb=(0.0, 0.0, 1.0),
        et=(1.0, 0.0, 0.0),
    )


# ---------------------------------------------------------------------------
# Test 1: Cube exterior edge → convex 90°
# ---------------------------------------------------------------------------

def test_cube_exterior_edge_convex_90():
    """Cube exterior 90° edge must classify as 'convex'."""
    samples = [_cube_corner_sample(0.25), _cube_corner_sample(0.5), _cube_corner_sample(0.75)]
    report = classify_edge_convexity(samples)
    assert report.classification == "convex", f"expected convex, got {report.classification!r}"
    assert report.num_samples == 3
    assert abs(report.mean_dihedral_deg - 90.0) < 1e-6, (
        f"expected 90°, got {report.mean_dihedral_deg}"
    )


# ---------------------------------------------------------------------------
# Test 2: L-bracket interior edge → concave 90°
# ---------------------------------------------------------------------------

def test_l_bracket_interior_edge_concave_90():
    """L-bracket interior 90° edge must classify as 'concave'."""
    samples = [_l_bracket_sample(0.25), _l_bracket_sample(0.5), _l_bracket_sample(0.75)]
    report = classify_edge_convexity(samples)
    assert report.classification == "concave", f"expected concave, got {report.classification!r}"
    assert abs(report.mean_dihedral_deg - 90.0) < 1e-6, (
        f"expected 90°, got {report.mean_dihedral_deg}"
    )


# ---------------------------------------------------------------------------
# Test 3: Coplanar faces → tangent
# ---------------------------------------------------------------------------

def test_coplanar_faces_tangent():
    """Two coplanar faces (same normal, dihedral ≈ 0°) → 'tangent'."""
    na = (0.0, 0.0, 1.0)
    nb = (0.0, 0.0, 1.0)   # parallel normals → dihedral = arccos(1) = 0°
    et = (1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, tangent_tol_deg=2.0)
    assert report.classification == "tangent", f"expected tangent, got {report.classification!r}"
    assert report.mean_dihedral_deg < 2.0


# ---------------------------------------------------------------------------
# Test 4: Near-flat but above tangent_tol → smooth boundary check
# ---------------------------------------------------------------------------

def test_near_flat_above_tol_convex_or_concave():
    """5° dihedral with tangent_tol=2° should NOT be 'tangent'."""
    angle_rad = math.radians(5.0)
    # n_b is rotated 5° from n_a around Z: n_a = (0,1,0), n_b ≈ (sin5, cos5, 0)
    na = (0.0, 1.0, 0.0)
    nb = (math.sin(angle_rad), math.cos(angle_rad), 0.0)
    et = (0.0, 0.0, 1.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, tangent_tol_deg=2.0)
    assert report.classification != "tangent", (
        "5° dihedral with 2° tol should not be tangent"
    )
    assert abs(report.mean_dihedral_deg - 5.0) < 0.01


# ---------------------------------------------------------------------------
# Test 5: Sharp 170° edge → sharp-convex
# ---------------------------------------------------------------------------

def test_sharp_170_deg_sharp_convex():
    """170° dihedral (nearly flat convex) → 'sharp-convex'."""
    angle_rad = math.radians(170.0)
    na = (0.0, 0.0, 1.0)
    nb = (0.0, math.sin(angle_rad), math.cos(angle_rad))
    # n_a × n_b, then check sign relative to a tangent that makes it convex
    import numpy as np
    cross = np.cross(na, nb)
    # pick edge_tangent aligned with cross so sign > 0 → convex
    norm_cross = float(np.linalg.norm(cross))
    if norm_cross > 1e-10:
        et = tuple(float(v / norm_cross) for v in cross)
    else:
        et = (1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, sharp_threshold_deg=135.0)
    assert report.classification == "sharp-convex", (
        f"expected sharp-convex, got {report.classification!r}"
    )
    assert report.mean_dihedral_deg > 135.0


# ---------------------------------------------------------------------------
# Test 6: Sharp 170° edge → sharp-concave (flip sign)
# ---------------------------------------------------------------------------

def test_sharp_170_deg_sharp_concave():
    """170° dihedral with concave sign → 'sharp-concave'."""
    angle_rad = math.radians(170.0)
    na = (0.0, 0.0, 1.0)
    nb = (0.0, math.sin(angle_rad), math.cos(angle_rad))
    import numpy as np
    cross = np.cross(na, nb)
    norm_cross = float(np.linalg.norm(cross))
    if norm_cross > 1e-10:
        # flip to make sign negative → concave
        et = tuple(float(-v / norm_cross) for v in cross)
    else:
        et = (1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, sharp_threshold_deg=135.0)
    assert report.classification == "sharp-concave", (
        f"expected sharp-concave, got {report.classification!r}"
    )


# ---------------------------------------------------------------------------
# Test 7: Empty samples → smooth (graceful no-op)
# ---------------------------------------------------------------------------

def test_empty_samples_returns_smooth():
    """classify_edge_convexity([]) must return without error."""
    report = classify_edge_convexity([])
    assert isinstance(report, SampledEdgeConvexityReport)
    assert report.num_samples == 0
    assert report.classification == "smooth"
    assert report.mean_dihedral_deg == 0.0


# ---------------------------------------------------------------------------
# Test 8: Multi-sample mean/min/max statistics
# ---------------------------------------------------------------------------

def test_statistics_mean_min_max():
    """Report must carry accurate mean, min, max dihedral across samples."""
    angles_deg = [60.0, 90.0, 120.0]
    samples = []
    import numpy as np
    for a_deg in angles_deg:
        a = math.radians(a_deg)
        na = (0.0, 0.0, 1.0)
        nb = (0.0, math.sin(a), math.cos(a))
        cross = np.cross(na, nb)
        norm_c = float(np.linalg.norm(cross))
        et = tuple(float(v / norm_c) for v in cross) if norm_c > 1e-10 else (1.0, 0.0, 0.0)
        samples.append(_sample((0.0, 0.0, 0.0), na, nb, et))
    report = classify_edge_convexity(samples)
    assert abs(report.mean_dihedral_deg - 90.0) < 1e-4, (
        f"mean expected 90°, got {report.mean_dihedral_deg}"
    )
    assert abs(report.min_dihedral_deg - 60.0) < 1e-4, (
        f"min expected 60°, got {report.min_dihedral_deg}"
    )
    assert abs(report.max_dihedral_deg - 120.0) < 1e-4, (
        f"max expected 120°, got {report.max_dihedral_deg}"
    )
    assert report.num_samples == 3


# ---------------------------------------------------------------------------
# Test 9: Re-export from geom.__init__
# ---------------------------------------------------------------------------

def test_geom_init_reexport():
    """EdgeSample, SampledEdgeConvexityReport, classify_edge_convexity
    must be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import (  # noqa: F401
        EdgeSample as ES,
        SampledEdgeConvexityReport as SECR,
        classify_edge_convexity as cec,
    )
    assert callable(cec)
    assert ES is EdgeSample
    assert SECR is SampledEdgeConvexityReport


# ---------------------------------------------------------------------------
# Test 10: SampledEdgeConvexityReport has honest_caveat
# ---------------------------------------------------------------------------

def test_report_has_honest_caveat():
    """SampledEdgeConvexityReport.honest_caveat must be a non-empty string."""
    samples = [_cube_corner_sample()]
    report = classify_edge_convexity(samples)
    assert isinstance(report.honest_caveat, str)
    assert len(report.honest_caveat) > 20
    assert "Mantyla" in report.honest_caveat or "caller" in report.honest_caveat


# ---------------------------------------------------------------------------
# Test 11: 45° convex edge
# ---------------------------------------------------------------------------

def test_45_deg_convex():
    """45° convex edge (between 0° and 90°) → 'convex', not sharp."""
    angle_rad = math.radians(45.0)
    na = (0.0, 0.0, 1.0)
    nb = (0.0, math.sin(angle_rad), math.cos(angle_rad))
    import numpy as np
    cross = np.cross(na, nb)
    norm_c = float(np.linalg.norm(cross))
    et = tuple(float(v / norm_c) for v in cross) if norm_c > 1e-10 else (1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, sharp_threshold_deg=135.0)
    assert report.classification == "convex"
    assert abs(report.mean_dihedral_deg - 45.0) < 1e-4


# ---------------------------------------------------------------------------
# Test 12: 45° concave edge
# ---------------------------------------------------------------------------

def test_45_deg_concave():
    """45° concave edge → 'concave' (same angle, flipped sign)."""
    angle_rad = math.radians(45.0)
    na = (0.0, 0.0, 1.0)
    nb = (0.0, math.sin(angle_rad), math.cos(angle_rad))
    import numpy as np
    cross = np.cross(na, nb)
    norm_c = float(np.linalg.norm(cross))
    # Flip tangent → sign negative → concave
    et = tuple(float(-v / norm_c) for v in cross) if norm_c > 1e-10 else (-1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, sharp_threshold_deg=135.0)
    assert report.classification == "concave"
    assert abs(report.mean_dihedral_deg - 45.0) < 1e-4


# ---------------------------------------------------------------------------
# Test 13: Single sample → statistics = mean = min = max
# ---------------------------------------------------------------------------

def test_single_sample_statistics():
    """With one sample, mean == min == max."""
    samples = [_cube_corner_sample()]
    report = classify_edge_convexity(samples)
    assert report.mean_dihedral_deg == report.min_dihedral_deg == report.max_dihedral_deg
    assert report.num_samples == 1


# ---------------------------------------------------------------------------
# Test 14: Tangent tolerance customisation
# ---------------------------------------------------------------------------

def test_tangent_tol_customisation():
    """With tangent_tol=90° every near-right-angle edge is tangent."""
    samples = [_cube_corner_sample()]   # 90° dihedral
    report = classify_edge_convexity(samples, tangent_tol_deg=91.0)
    assert report.classification == "tangent", (
        "90° dihedral should be tangent when tol=91°"
    )


# ---------------------------------------------------------------------------
# Test 15: 135° edge → convex (just below sharp_threshold)
# ---------------------------------------------------------------------------

def test_135_deg_below_sharp_threshold():
    """135° convex edge with sharp_threshold=135° → 'convex' (not 'sharp-convex')
    because the condition is strictly greater than, not >=."""
    angle_rad = math.radians(135.0)
    na = (0.0, 0.0, 1.0)
    nb = (0.0, math.sin(angle_rad), math.cos(angle_rad))
    import numpy as np
    cross = np.cross(na, nb)
    norm_c = float(np.linalg.norm(cross))
    et = tuple(float(v / norm_c) for v in cross) if norm_c > 1e-10 else (1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, sharp_threshold_deg=135.0)
    # 135° is NOT > 135°, so should be plain convex
    assert report.classification == "convex", (
        f"135° at threshold=135° should be 'convex', got {report.classification!r}"
    )


# ---------------------------------------------------------------------------
# Test 16: 136° edge → sharp-convex (just above sharp_threshold)
# ---------------------------------------------------------------------------

def test_136_deg_above_sharp_threshold():
    """136° convex edge with sharp_threshold=135° → 'sharp-convex'."""
    angle_rad = math.radians(136.0)
    na = (0.0, 0.0, 1.0)
    nb = (0.0, math.sin(angle_rad), math.cos(angle_rad))
    import numpy as np
    cross = np.cross(na, nb)
    norm_c = float(np.linalg.norm(cross))
    et = tuple(float(v / norm_c) for v in cross) if norm_c > 1e-10 else (1.0, 0.0, 0.0)
    samples = [_sample((0.0, 0.0, 0.0), na, nb, et)]
    report = classify_edge_convexity(samples, sharp_threshold_deg=135.0)
    assert report.classification == "sharp-convex", (
        f"136° at threshold=135° should be 'sharp-convex', got {report.classification!r}"
    )
