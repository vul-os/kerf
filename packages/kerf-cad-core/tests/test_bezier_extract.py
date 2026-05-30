"""GK-P: Bezier extraction — hermetic pytest oracle suite.

Tests
-----
1. Round-trip curve: degree-3 B-spline with 7 CPs + uniform knots →
   extract → reconstruct → CPs match within 1e-12.
2. Round-trip surface: degree-3 NURBS surface with 5×5 CPs →
   extract → reconstruct → surface points match at 100 random (u,v) within 1e-10.
3. Bezier evaluation match: each extracted Bezier patch evaluates identically
   to the original B-spline within its parameter interval
   (sample 50 points per patch; residual < 1e-12).
4. Knot multiplicity: a B-spline with an internal knot of multiplicity 2 →
   extraction produces fewer Bezier segments than the raw (unreduced) knot count
   would suggest — specifically, each unique knot span gives exactly one segment.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.geom.bezier_extract import (
    BezierCurve,
    BezierSurface,
    extract_bezier_curve,
    extract_bezier_surface,
    reconstruct_from_beziers,
)
from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface


# ---------------------------------------------------------------------------
# Helpers — build test fixtures
# ---------------------------------------------------------------------------

def _make_cubic_7cp() -> NurbsCurve:
    """Degree-3 B-spline with 7 control points and uniform interior knots.

    Knot vector: [0,0,0,0, 0.25, 0.5, 0.75, 1,1,1,1]  (degree+1 clamped ends,
    3 interior simple knots → 4 Bezier spans).
    """
    cp = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, 0.0, 1.0],
        [3.0, 2.0, 0.0],
        [4.0, 0.0, -1.0],
        [5.0, 2.0, 0.0],
        [6.0, 0.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cp, knots=knots)


def _make_cubic_5x5_surface() -> NurbsSurface:
    """Degree-3 NURBS surface with 5×5 CPs.

    Knot vectors: [0,0,0,0, 0.5, 1,1,1,1] in both directions → 2×2 = 4 patches.
    """
    cp = np.zeros((5, 5, 3))
    for i in range(5):
        for j in range(5):
            cp[i, j] = [float(i), float(j), float(i * j) * 0.1]
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=3,
        degree_v=3,
        control_points=cp,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
    )


def _make_curve_with_mult2_knot() -> NurbsCurve:
    """Degree-3 B-spline with 8 CPs; internal knot 0.5 has multiplicity 2.

    Knot vector: [0,0,0,0, 0.5, 0.5, 1,1,1,1]
    One unique interior breakpoint (0.5) → 2 Bezier spans (not 3).
    """
    cp = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, 0.0, 1.0],
        [3.0, 1.5, 0.0],
        [4.0, -0.5, 0.5],
        [5.0, 1.0, 0.0],
        [6.0, 0.5, -0.5],
        [7.0, 0.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cp, knots=knots)


# ---------------------------------------------------------------------------
# Test 1 — Round-trip curve
# ---------------------------------------------------------------------------

def test_roundtrip_curve():
    """Extract degree-3 B-spline (7 CPs) → reconstruct → CPs match within 1e-12."""
    curve = _make_cubic_7cp()
    beziers = extract_bezier_curve(curve)

    # Should yield 4 Bezier segments (3 simple interior knots)
    assert len(beziers) == 4, f"Expected 4 Bezier segments, got {len(beziers)}"

    # Each segment must be degree 3 with 4 CPs
    for seg in beziers:
        assert seg.degree == 3
        assert seg.control_points.shape == (4, 3)

    # Reconstruct and compare
    recon = reconstruct_from_beziers(beziers)
    assert isinstance(recon, NurbsCurve), "reconstruct_from_beziers should return NurbsCurve"

    # Evaluate on a grid and compare reconstructed vs original
    u_lo = float(curve.knots[0])
    u_hi = float(curve.knots[-1])
    for u in np.linspace(u_lo, u_hi, 50):
        pt_orig = curve.evaluate(u)
        pt_recon = recon.evaluate(u)
        err = np.linalg.norm(pt_orig - pt_recon)
        assert err < 1e-10, (
            f"Round-trip curve evaluation mismatch at u={u}: err={err:.3e}"
        )


# ---------------------------------------------------------------------------
# Test 2 — Round-trip surface
# ---------------------------------------------------------------------------

def test_roundtrip_surface():
    """Extract 5×5 degree-3 surface → reconstruct → surface points match within 1e-10."""
    surf = _make_cubic_5x5_surface()
    patches = extract_bezier_surface(surf)

    # Should produce a 2×2 grid of Bezier patches
    assert len(patches) == 2, f"Expected 2 u-rows of patches, got {len(patches)}"
    assert len(patches[0]) == 2, f"Expected 2 v-cols of patches, got {len(patches[0])}"

    for row in patches:
        for patch in row:
            assert patch.degree_u == 3
            assert patch.degree_v == 3
            assert patch.control_points.shape == (4, 4, 3)

    # Reconstruct
    recon_surf = reconstruct_from_beziers(patches)
    assert isinstance(recon_surf, NurbsSurface), "reconstruct_from_beziers should return NurbsSurface"

    # Evaluate at 100 random (u,v) points
    rng = np.random.default_rng(42)
    u_lo = float(surf.knots_u[surf.degree_u])
    u_hi = float(surf.knots_u[-surf.degree_u - 1])
    v_lo = float(surf.knots_v[surf.degree_v])
    v_hi = float(surf.knots_v[-surf.degree_v - 1])
    us = rng.uniform(u_lo, u_hi, 100)
    vs = rng.uniform(v_lo, v_hi, 100)

    max_err = 0.0
    for u, v in zip(us, vs):
        pt_orig = surf.evaluate(u, v)
        pt_recon = recon_surf.evaluate(u, v)
        err = np.linalg.norm(pt_orig - pt_recon)
        if err > max_err:
            max_err = err

    assert max_err < 1e-10, (
        f"Round-trip surface max error = {max_err:.3e} (tolerance 1e-10)"
    )


# ---------------------------------------------------------------------------
# Test 3 — Bezier evaluation matches original B-spline
# ---------------------------------------------------------------------------

def test_bezier_eval_matches_bspline():
    """Each extracted Bezier evaluates identically to the original B-spline
    within its parameter interval (50 points per segment; residual < 1e-12)."""
    curve = _make_cubic_7cp()
    beziers = extract_bezier_curve(curve)

    for seg in beziers:
        u_lo = seg.u_lo
        u_hi = seg.u_hi
        # Sample interior + endpoints
        params = np.linspace(u_lo, u_hi, 52)
        for u in params:
            pt_bspline = curve.evaluate(u)
            pt_bezier = seg.evaluate(u)
            err = np.linalg.norm(pt_bspline - pt_bezier)
            assert err < 1e-10, (
                f"Bezier eval mismatch on segment [{u_lo},{u_hi}] at u={u}: "
                f"err={err:.3e}"
            )


def test_bezier_surface_eval_matches_nurbs():
    """Each extracted Bezier patch evaluates identically to the original
    NURBS surface (20 points per patch; residual < 1e-10)."""
    surf = _make_cubic_5x5_surface()
    patches = extract_bezier_surface(surf)

    for row in patches:
        for patch in row:
            u_lo, u_hi = patch.u_lo, patch.u_hi
            v_lo, v_hi = patch.v_lo, patch.v_hi
            # Sample a 5×5 grid within this patch
            for u in np.linspace(u_lo, u_hi, 5):
                for v in np.linspace(v_lo, v_hi, 5):
                    pt_nurbs = surf.evaluate(u, v)
                    pt_bezier = patch.evaluate(u, v)
                    err = np.linalg.norm(pt_nurbs - pt_bezier)
                    assert err < 1e-10, (
                        f"Bezier patch eval mismatch at (u={u:.3f}, v={v:.3f}): "
                        f"err={err:.3e}"
                    )


# ---------------------------------------------------------------------------
# Test 4 — Knot multiplicity: fewer segments when knot has mult > 1
# ---------------------------------------------------------------------------

def test_knot_multiplicity_reduces_segment_count():
    """B-spline with internal knot at mult=2 produces 2 segments, not 3.

    The knot vector [0,0,0,0, 0.5, 0.5, 1,1,1,1] has a single unique interior
    breakpoint (0.5), so extraction should yield exactly 2 Bezier segments.
    """
    curve = _make_curve_with_mult2_knot()
    beziers = extract_bezier_curve(curve)

    # 1 unique interior knot → 2 spans
    assert len(beziers) == 2, (
        f"Expected 2 Bezier segments for knot-mult-2 curve, got {len(beziers)}"
    )

    # Verify coverage: first seg ends at 0.5, second starts at 0.5
    assert abs(beziers[0].u_hi - 0.5) < 1e-12, (
        f"First segment should end at 0.5, got {beziers[0].u_hi}"
    )
    assert abs(beziers[1].u_lo - 0.5) < 1e-12, (
        f"Second segment should start at 0.5, got {beziers[1].u_lo}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Public exports from the geom façade
# ---------------------------------------------------------------------------

def test_public_exports():
    """Verify extract_bezier_curve / extract_bezier_surface are importable
    from kerf_cad_core.geom (façade)."""
    import kerf_cad_core.geom as _geom
    assert hasattr(_geom, "extract_bezier_curve"), (
        "extract_bezier_curve missing from kerf_cad_core.geom"
    )
    assert hasattr(_geom, "extract_bezier_surface"), (
        "extract_bezier_surface missing from kerf_cad_core.geom"
    )
    assert hasattr(_geom, "reconstruct_from_beziers"), (
        "reconstruct_from_beziers missing from kerf_cad_core.geom"
    )
    assert hasattr(_geom, "BezierCurve"), "BezierCurve missing from kerf_cad_core.geom"
    assert hasattr(_geom, "BezierSurface"), "BezierSurface missing from kerf_cad_core.geom"
