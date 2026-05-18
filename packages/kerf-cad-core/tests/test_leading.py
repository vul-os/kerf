"""
test_leading.py
===============
Hermetic tests for kerf_cad_core.geom.leading — Class-A leading surface
quality / hot-spot flagging pass (T-104h).

All tests are pure-Python: no OCC, no database, no network.

Analytic oracle surfaces:

  perfect_class_a   : Degree-3 C3-continuous NURBS plane with zero curvature
                      everywhere — zero hot-spots above threshold.

  g2_only_surface   : Two degree-3 patches stitched with a G2 (but NOT G3)
                      seam; must produce ≥1 'g3-dropout' hot-spot.

  comb_peak_surface : A pointed paraboloid with a high curvature apex; must
                      produce ≥1 'comb-peak' hot-spot.

  zebra_break_surface: A surface with an intentional sharp normal discontinuity
                       that manifests as a zebra-break.

Coverage
--------
* LeadingReport and LeadingHotspot data types exposed correctly.
* run_leading_pass returns LeadingReport.ok=True for a valid surface.
* Invalid input returns ok=False with a reason string (never raises).
* Perfect Class-A surface produces zero hotspots above threshold.
* G2-only fixture produces ≥1 'g3-dropout' hotspot — **primary oracle**.
* Comb-peak fixture produces ≥1 'comb-peak' hotspot.
* All detected hotspot severities are > 0 and finite.
* All hotspot kinds are from the defined set.
* Hotspots are sorted in descending severity order.
* Threshold override: raising g3_threshold silences G3 hot-spots.
* nu/nv override: analysis completes and ok=True.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.leading import (
    LeadingHotspot,
    LeadingReport,
    run_leading_pass,
)

# ---------------------------------------------------------------------------
# Shared surface factories
# ---------------------------------------------------------------------------

def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts: List[np.ndarray] = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def make_perfect_class_a_surface() -> NurbsSurface:
    """Degree-3, C3-continuous flat plane z=0.

    This is the simplest Class-A compliant surface: a polynomial flat NURBS
    with no curvature variation, no zebra discontinuities, and analytic G3
    continuity.  The leading pass must produce zero hotspots above the
    default threshold for this surface.

    Uses a 6×6 control grid (min for degree-3) with uniform knots so the
    surface is a polynomial bilinear patch — K=H=k1=k2=0 everywhere.
    """
    deg = 3
    nu, nv = 6, 6
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [float(i) / (nu - 1), float(j) / (nv - 1), 0.0]
    return NurbsSurface(
        degree_u=deg,
        degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_g2_only_surface() -> NurbsSurface:
    """Degree-3 NURBS surface with a deliberate G2-only (not G3) seam.

    Construction: a flat base plane (H=0), but with the interior control
    points perturbed so that the second derivative of H is non-zero at the
    midline.  Specifically, we introduce a curvature ramp that is symmetric
    (so G2 is preserved) but not smooth in the third derivative (Δ²H != 0).

    The surface is built on a 8×4 control grid.  The u-midline control points
    are given a z-bulge that creates a matched curvature discontinuity in the
    third order: the second row on each side of the midline has the same
    curvature magnitude but a step in the curvature rate (Δ²H is large at
    the seam row).

    This fixture is the primary oracle for the 'g3-dropout' detection test.
    """
    deg = 3
    nu, nv = 8, 6
    cp = np.zeros((nu, nv, 3))

    # Base grid: uniform in u, uniform in v.
    for i in range(nu):
        for j in range(nv):
            x = float(i) / (nu - 1)
            y = float(j) / (nv - 1)
            cp[i, j] = [x, y, 0.0]

    # Introduce a localised z-bump that is G2-matched across the midline
    # but has a step in the third derivative (Δ³z ≠ 0).
    # We give rows 2 and 3 (just before the midline) a gentle curve, while
    # rows 4 and 5 (just after) have a steeper slope, creating a step in
    # the curvature rate.  The curvature values at the seam (i=3, i=4) are
    # equal (G2 is maintained by construction), but the second differences
    # differ (G3 dropout).
    amplitude = 0.4
    for j in range(nv):
        # Parabolic bump: z = amplitude * (x - 0.5)^2 * bump_factor
        # Rows 1-3: shallow curvature
        cp[1, j, 2] = 0.02 * amplitude
        cp[2, j, 2] = 0.06 * amplitude
        cp[3, j, 2] = 0.12 * amplitude   # at seam row — left side
        # Rows 4-6: steeper curvature (same curvature at seam, larger Δk)
        cp[4, j, 2] = 0.12 * amplitude   # at seam row — right side (G2 matched)
        cp[5, j, 2] = 0.28 * amplitude   # larger step → G3 dropout
        cp[6, j, 2] = 0.06 * amplitude

    return NurbsSurface(
        degree_u=deg,
        degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


def make_comb_peak_surface() -> NurbsSurface:
    """Degree-2 paraboloid with a sharp curvature apex — triggers comb-peak."""
    deg = 2
    nu, nv = 7, 7
    cp = np.zeros((nu, nv, 3))
    c = 2.0  # strong curvature; k1 >> median for most of the surface
    for i in range(nu):
        x = (float(i) / (nu - 1)) * 2.0 - 1.0   # [-1, +1]
        for j in range(nv):
            y = (float(j) / (nv - 1)) * 2.0 - 1.0
            cp[i, j] = [x, y, c * (x * x + y * y)]
    return NurbsSurface(
        degree_u=deg,
        degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


# ---------------------------------------------------------------------------
# Tests: data types
# ---------------------------------------------------------------------------

class TestLeadingDataTypes:
    def test_hotspot_fields_exist(self):
        h = LeadingHotspot(
            location=(0.5, 0.5),
            severity=1.2,
            kind="g3-dropout",
            context="test",
        )
        assert h.location == (0.5, 0.5)
        assert h.severity == 1.2
        assert h.kind == "g3-dropout"
        assert h.context == "test"

    def test_report_fields_exist(self):
        r = LeadingReport(hotspots=[], ok=True, reason="")
        assert r.hotspots == []
        assert r.ok is True
        assert r.reason == ""

    def test_report_default_ok(self):
        r = LeadingReport()
        assert r.ok is True

    def test_report_default_empty_hotspots(self):
        r = LeadingReport()
        assert isinstance(r.hotspots, list)
        assert len(r.hotspots) == 0


# ---------------------------------------------------------------------------
# Tests: invalid input guard
# ---------------------------------------------------------------------------

class TestLeadingInvalidInput:
    def test_non_nurbs_surface_returns_not_ok(self):
        result = run_leading_pass("not a surface")  # type: ignore[arg-type]
        assert result.ok is False
        assert len(result.reason) > 0
        assert len(result.hotspots) == 0

    def test_none_surface_returns_not_ok(self):
        result = run_leading_pass(None)  # type: ignore[arg-type]
        assert result.ok is False

    def test_never_raises_on_bad_input(self):
        # Must not raise regardless of input type.
        try:
            run_leading_pass(42)  # type: ignore[arg-type]
        except Exception as exc:
            pytest.fail(f"run_leading_pass raised {exc!r} on bad input")


# ---------------------------------------------------------------------------
# Tests: perfect Class-A surface → zero hot-spots
# ---------------------------------------------------------------------------

class TestPerfectClassASurface:
    def test_ok_true(self):
        surf = make_perfect_class_a_surface()
        report = run_leading_pass(surf)
        assert report.ok is True

    def test_zero_hotspots_above_threshold(self):
        """The perfect flat degree-3 surface must produce no hotspots."""
        surf = make_perfect_class_a_surface()
        report = run_leading_pass(surf)
        assert len(report.hotspots) == 0, (
            f"Expected 0 hotspots but got {len(report.hotspots)}: "
            + "; ".join(f"{h.kind}@{h.location}" for h in report.hotspots[:5])
        )

    def test_reason_empty_on_success(self):
        surf = make_perfect_class_a_surface()
        report = run_leading_pass(surf)
        assert report.reason == ""


# ---------------------------------------------------------------------------
# Tests: G2-only fixture → ≥1 g3-dropout  [PRIMARY ORACLE]
# ---------------------------------------------------------------------------

class TestG2OnlySurface:
    def test_ok_true(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf, g3_threshold=1e-3)
        assert report.ok is True

    def test_produces_at_least_one_g3_dropout(self):
        """A G2-only surface must expose ≥1 g3-dropout hot-spot."""
        surf = make_g2_only_surface()
        report = run_leading_pass(surf, g3_threshold=1e-3)
        g3_spots = [h for h in report.hotspots if h.kind == "g3-dropout"]
        assert len(g3_spots) >= 1, (
            f"Expected ≥1 g3-dropout hotspot but got {len(g3_spots)}; "
            f"all hotspots: {[(h.kind, h.severity) for h in report.hotspots[:10]]}"
        )

    def test_g3_dropout_severity_positive(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf, g3_threshold=1e-3)
        g3_spots = [h for h in report.hotspots if h.kind == "g3-dropout"]
        for h in g3_spots:
            assert h.severity > 0.0
            assert math.isfinite(h.severity)

    def test_g3_dropout_context_non_empty(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf, g3_threshold=1e-3)
        g3_spots = [h for h in report.hotspots if h.kind == "g3-dropout"]
        for h in g3_spots:
            assert isinstance(h.context, str)
            assert len(h.context) > 0

    def test_raising_threshold_silences_g3_hotspots(self):
        """Setting g3_threshold very high should eliminate g3-dropout flags."""
        surf = make_g2_only_surface()
        report_high = run_leading_pass(surf, g3_threshold=1e9)
        g3_spots = [h for h in report_high.hotspots if h.kind == "g3-dropout"]
        assert len(g3_spots) == 0, (
            f"Expected 0 g3-dropout with high threshold but got {len(g3_spots)}"
        )


# ---------------------------------------------------------------------------
# Tests: comb-peak surface → ≥1 comb-peak hot-spot
# ---------------------------------------------------------------------------

class TestCombPeakSurface:
    def test_ok_true(self):
        surf = make_comb_peak_surface()
        report = run_leading_pass(surf)
        assert report.ok is True

    def test_produces_at_least_one_comb_peak(self):
        """Sharp paraboloid must produce ≥1 comb-peak hotspot."""
        surf = make_comb_peak_surface()
        report = run_leading_pass(surf, comb_threshold=2.0)
        comb_spots = [h for h in report.hotspots if h.kind == "comb-peak"]
        assert len(comb_spots) >= 1, (
            f"Expected ≥1 comb-peak but got {len(comb_spots)}; "
            f"all: {[(h.kind, h.severity) for h in report.hotspots[:10]]}"
        )

    def test_comb_peak_severity_finite(self):
        surf = make_comb_peak_surface()
        report = run_leading_pass(surf, comb_threshold=2.0)
        for h in report.hotspots:
            assert math.isfinite(h.severity), f"Non-finite severity: {h}"
            assert h.severity > 0.0


# ---------------------------------------------------------------------------
# Tests: hotspot invariants
# ---------------------------------------------------------------------------

class TestHotspotInvariants:
    def test_kind_is_valid(self):
        """Every hotspot kind must be one of the three valid strings."""
        valid_kinds = {"comb-peak", "zebra-break", "g3-dropout"}
        surf = make_g2_only_surface()
        report = run_leading_pass(surf)
        for h in report.hotspots:
            assert h.kind in valid_kinds, f"Unknown kind: {h.kind!r}"

    def test_location_is_tuple_of_two_floats(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf)
        for h in report.hotspots:
            assert isinstance(h.location, tuple)
            assert len(h.location) == 2
            assert all(math.isfinite(c) for c in h.location)

    def test_hotspots_sorted_descending_severity(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf)
        severities = [h.severity for h in report.hotspots]
        assert severities == sorted(severities, reverse=True), (
            "Hotspots not sorted in descending severity order"
        )

    def test_severity_all_positive(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf)
        for h in report.hotspots:
            assert h.severity > 0.0

    def test_severity_all_finite(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf)
        for h in report.hotspots:
            assert math.isfinite(h.severity)


# ---------------------------------------------------------------------------
# Tests: grid parameter override
# ---------------------------------------------------------------------------

class TestGridOverride:
    def test_coarse_grid_completes_ok(self):
        surf = make_g2_only_surface()
        report = run_leading_pass(surf, nu=8, nv=8)
        assert report.ok is True

    def test_fine_grid_completes_ok(self):
        surf = make_perfect_class_a_surface()
        report = run_leading_pass(surf, nu=40, nv=40)
        assert report.ok is True

    def test_extreme_small_nu_nv_clamped(self):
        """nu/nv below the minimum (5) should be silently clamped — no crash."""
        surf = make_perfect_class_a_surface()
        report = run_leading_pass(surf, nu=1, nv=1)
        assert report.ok is True
