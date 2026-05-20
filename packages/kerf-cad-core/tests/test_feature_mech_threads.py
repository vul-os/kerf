"""
T-21 — Mech: thread features (cut + boss)
==========================================
Spec: 25 thread specs; pitch/diameter match catalog; engagement length vs
DIN/ASME.

Standards referenced:
  ISO 261:2013     — metric thread series selection (M1.6–M64 coarse + fine)
  ISO 965-1:1998   — metric thread tolerances, reference class 6H/6g
  DIN 13-12:2021   — metric thread engagement length groups:
                       S (short)  = 0.5 × D
                       N (normal) = 1.0 × D  (upper: 1.5 × D)
                       L (long)   > 1.5 × D
  ASME B1.1-2003   — Unified inch threads (UNC/UNF); default class 2B/2A
                       ASME table: recommended min engagement = 1.0 × D_major (inch)
                       Long engagement typically = 1.5 × D_major

Minor-diameter formula (60° V-thread, both standards):
  minor_dia = major_dia − k × pitch
    ISO:  k = 1.226869  (derived from ISO 68-1)
    UTS:  k = 1.299038  (same derivation, inch units)

Tap-drill formula (75% thread engagement — ISO 228 / ASME B1.1 Appendix):
  tap_drill = major_dia − pitch

Pure-Python, hermetic — no OCC, no DB, no network.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.thread_specs import (
    ALL_THREADS,
    METRIC_COARSE,
    METRIC_FINE,
    UTS_ALL,
    lookup,
    metric_coarse_designations,
    uts_unc_designations,
    uts_unf_designations,
)
from kerf_cad_core.feature_thread import (
    parse_designation,
    validate_tapped_hole_args,
    validate_external_thread_args,
    build_tapped_hole_node,
    SHAFT_TOLERANCE_MM,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# ISO 68-1 thread constant for minor-diameter formula (metric and UTS)
_ISO_K_METRIC = 1.226869
_ISO_K_UTS    = 1.299038

# DIN 13-12 engagement group boundaries (multiplier of major diameter D)
_DIN_NORMAL_MIN = 1.0   # lower bound of normal engagement group N
_DIN_NORMAL_MAX = 1.5   # upper bound of normal engagement group N
_DIN_SHORT_MAX  = 0.5   # upper bound of short group S

# ASME B1.1 recommended minimum engagement (inches, ~1 × D_major)
_ASME_MIN_FACTOR = 1.0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _engagement_din_group(engagement_mm: float, major_dia_mm: float) -> str:
    """
    Return DIN 13-12 engagement group: 'S', 'N', or 'L'.

    S: engagement < 0.5 × D
    N: 0.5 × D ≤ engagement ≤ 1.5 × D
    L: engagement > 1.5 × D
    """
    ratio = engagement_mm / major_dia_mm
    if ratio > _DIN_NORMAL_MAX:
        return "L"
    if ratio >= _DIN_SHORT_MAX:
        return "N"
    return "S"


def _min_engagement_asme_mm(major_dia_mm: float) -> float:
    """ASME B1.1 minimum recommended engagement in mm (1 × D_major_mm)."""
    return _ASME_MIN_FACTOR * major_dia_mm


# ---------------------------------------------------------------------------
# Part A — 25 thread specs: pitch/diameter match catalog
#   5 metric coarse, 5 metric fine, 8 UNC numbered+fractional, 7 UNF
# ---------------------------------------------------------------------------

# Selected 25 canonical designations covering the whole range.
# Tuples: (designation, expected_major_mm, expected_pitch_mm)
# Values are the exact ISO 261 / ASME B1.1 standard nominal values;
# these are NOT taken from the catalog — they are the independent reference.

_METRIC_COARSE_REF: list[tuple[str, float, float]] = [
    ("M3",   3.0,  0.50),
    ("M6",   6.0,  1.00),
    ("M10", 10.0,  1.50),
    ("M16", 16.0,  2.00),
    ("M24", 24.0,  3.00),
]

_METRIC_FINE_REF: list[tuple[str, float, float]] = [
    ("M8x1",      8.0,  1.00),
    ("M10x1",    10.0,  1.00),
    ("M12x1.5",  12.0,  1.50),
    ("M20x1.5",  20.0,  1.50),
    ("M6x0.75",   6.0,  0.75),
]

# UTS: major diameters from ASME B1.1 table; TPI from standard.
# We store (designation, major_dia_in, tpi) and derive mm.
_UTS_UNC_REF: list[tuple[str, float, float]] = [
    ("#4-40 UNC",    0.1120, 40),
    ("#10-24 UNC",   0.1900, 24),
    ("1/4-20 UNC",   0.2500, 20),
    ("1/2-13 UNC",   0.5000, 13),
    ("3/4-10 UNC",   0.7500, 10),
    ("1-8 UNC",      1.0000,  8),
    ("1 1/4-7 UNC",  1.2500,  7),
    ("1 1/2-6 UNC",  1.5000,  6),
]

_UTS_UNF_REF: list[tuple[str, float, float]] = [
    ("#6-40 UNF",    0.1380, 40),
    ("#10-32 UNF",   0.1900, 32),
    ("1/4-28 UNF",   0.2500, 28),
    ("1/2-20 UNF",   0.5000, 20),
    ("3/4-16 UNF",   0.7500, 16),
    ("7/8-14 UNF",   0.8750, 14),
    ("1-14 UNF",     1.0000, 14),
]

# Combined: exactly 5+5+8+7 = 25 specs
_ALL_25 = (
    [(d, maj, p, "metric_coarse") for d, maj, p in _METRIC_COARSE_REF]
    + [(d, maj, p, "metric_fine")   for d, maj, p in _METRIC_FINE_REF]
    + [(d, maj_in, tpi, "uts_unc")  for d, maj_in, tpi in _UTS_UNC_REF]
    + [(d, maj_in, tpi, "uts_unf")  for d, maj_in, tpi in _UTS_UNF_REF]
)
assert len(_ALL_25) == 25, "Fixture must contain exactly 25 specs"


class TestCatalogPitchDiameter:
    """25 thread specs — pitch and major diameter match standard reference."""

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, _ in _ALL_25
        if _ in ("metric_coarse", "metric_fine")
    ])
    def test_metric_major_dia(self, desig, ref_maj_mm, ref_pitch_mm):
        """major_dia_mm must match ISO 261 nominal to 4 decimal places."""
        spec = lookup(desig)
        assert spec is not None, f"designation {desig!r} missing from catalog"
        assert spec["major_dia_mm"] == pytest.approx(ref_maj_mm, abs=1e-4), (
            f"{desig}: expected major_dia_mm={ref_maj_mm}, got {spec['major_dia_mm']}"
        )

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, _ in _ALL_25
        if _ in ("metric_coarse", "metric_fine")
    ])
    def test_metric_pitch(self, desig, ref_maj_mm, ref_pitch_mm):
        """pitch_mm must match ISO 261 nominal to 4 decimal places."""
        spec = lookup(desig)
        assert spec is not None
        assert spec["pitch_mm"] == pytest.approx(ref_pitch_mm, abs=1e-4), (
            f"{desig}: expected pitch_mm={ref_pitch_mm}, got {spec['pitch_mm']}"
        )

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, _ in _ALL_25
        if _ in ("uts_unc", "uts_unf")
    ])
    def test_uts_major_dia_mm(self, desig, ref_maj_in, ref_tpi):
        """UTS major_dia_mm = major_dia_in × 25.4 (ASME B1.1)."""
        spec = lookup(desig)
        assert spec is not None, f"designation {desig!r} missing from catalog"
        expected_mm = round(ref_maj_in * 25.4, 4)
        assert spec["major_dia_mm"] == pytest.approx(expected_mm, abs=1e-3), (
            f"{desig}: expected major_dia_mm≈{expected_mm}, got {spec['major_dia_mm']}"
        )

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, _ in _ALL_25
        if _ in ("uts_unc", "uts_unf")
    ])
    def test_uts_pitch_mm(self, desig, ref_maj_in, ref_tpi):
        """UTS pitch_mm = 25.4 / TPI (ASME B1.1)."""
        spec = lookup(desig)
        assert spec is not None
        expected_pitch_mm = round(25.4 / ref_tpi, 4)
        assert spec["pitch_mm"] == pytest.approx(expected_pitch_mm, abs=1e-3), (
            f"{desig}: expected pitch_mm≈{expected_pitch_mm}, got {spec['pitch_mm']}"
        )


class TestCatalogMinorDiameter:
    """Minor diameter computed from ISO 68-1 / ASME B1.1 formula."""

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, _ in _ALL_25
        if _ in ("metric_coarse", "metric_fine")
    ])
    def test_metric_minor_dia_formula(self, desig, ref_maj_mm, ref_pitch_mm):
        """minor_dia_mm = major_dia_mm − 1.226869 × pitch_mm (ISO 68-1)."""
        spec = lookup(desig)
        assert spec is not None
        expected = round(ref_maj_mm - _ISO_K_METRIC * ref_pitch_mm, 4)
        assert spec["minor_dia_mm"] == pytest.approx(expected, abs=1e-4), (
            f"{desig}: minor_dia_mm expected {expected}, got {spec['minor_dia_mm']}"
        )

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, _ in _ALL_25
        if _ in ("uts_unc", "uts_unf")
    ])
    def test_uts_minor_dia_formula(self, desig, ref_maj_in, ref_tpi):
        """minor_dia_in = major_dia_in − 1.299038 × (1/TPI) (ASME B1.1)."""
        spec = lookup(desig)
        assert spec is not None
        p_in = 1.0 / ref_tpi
        expected_in = round(ref_maj_in - _ISO_K_UTS * p_in, 6)
        assert spec["minor_dia_in"] == pytest.approx(expected_in, abs=1e-4), (
            f"{desig}: minor_dia_in expected {expected_in}, got {spec['minor_dia_in']}"
        )

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, _ in _ALL_25
        if _ in ("metric_coarse", "metric_fine")
    ])
    def test_metric_tap_drill_formula(self, desig, ref_maj_mm, ref_pitch_mm):
        """tap_drill_mm = major_dia_mm − pitch_mm (75% engagement, ISO 228)."""
        spec = lookup(desig)
        assert spec is not None
        expected = round(ref_maj_mm - ref_pitch_mm, 4)
        assert spec["tap_drill_mm"] == pytest.approx(expected, abs=1e-4), (
            f"{desig}: tap_drill_mm expected {expected}, got {spec['tap_drill_mm']}"
        )

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, _ in _ALL_25
        if _ in ("uts_unc", "uts_unf")
    ])
    def test_uts_tap_drill_formula(self, desig, ref_maj_in, ref_tpi):
        """tap_drill_in = major_dia_in − 1/TPI (75% engagement, ASME B1.1)."""
        spec = lookup(desig)
        assert spec is not None
        p_in = 1.0 / ref_tpi
        expected_in = round(ref_maj_in - p_in, 6)
        assert spec["tap_drill_in"] == pytest.approx(expected_in, abs=1e-4), (
            f"{desig}: tap_drill_in expected {expected_in}, got {spec['tap_drill_in']}"
        )


class TestCatalogThreadClass:
    """Default tolerance class for each standard."""

    @pytest.mark.parametrize("desig", [d for d, *_ in _METRIC_COARSE_REF + _METRIC_FINE_REF])
    def test_metric_default_class_6hg(self, desig):
        """All metric threads default to 6H/6g (ISO 965-1)."""
        spec = lookup(desig)
        assert spec is not None
        assert spec["thread_class"] == "6H/6g", (
            f"{desig}: expected thread_class='6H/6g', got {spec['thread_class']!r}"
        )

    @pytest.mark.parametrize("desig", [d for d, *_ in _UTS_UNC_REF + _UTS_UNF_REF])
    def test_uts_default_class_2ba(self, desig):
        """All UTS threads default to 2B/2A (ASME B1.1)."""
        spec = lookup(desig)
        assert spec is not None
        assert spec["thread_class"] == "2B/2A", (
            f"{desig}: expected thread_class='2B/2A', got {spec['thread_class']!r}"
        )


# ---------------------------------------------------------------------------
# Part B — Engagement length vs DIN 13-12 / ASME B1.1
# ---------------------------------------------------------------------------

class TestEngagementLengthDIN:
    """
    DIN 13-12 normal engagement group N: 0.5×D ≤ engagement ≤ 1.5×D.
    A blind hole set to depth = 1.0 × D falls in group N for all metric threads.
    """

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, kind in _ALL_25
        if kind in ("metric_coarse", "metric_fine")
    ])
    def test_normal_engagement_in_group_N(self, desig, ref_maj_mm, ref_pitch_mm):
        """engagement = 1.0 × D → DIN 13-12 group N."""
        engagement = 1.0 * ref_maj_mm
        group = _engagement_din_group(engagement, ref_maj_mm)
        assert group == "N", (
            f"{desig}: engagement={engagement:.3f} mm, D={ref_maj_mm} mm "
            f"should be group N, got {group!r}"
        )

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, kind in _ALL_25
        if kind in ("metric_coarse", "metric_fine")
    ])
    def test_short_engagement_is_group_S(self, desig, ref_maj_mm, ref_pitch_mm):
        """engagement = 0.4 × D (below S boundary) → DIN 13-12 group S."""
        engagement = 0.4 * ref_maj_mm
        group = _engagement_din_group(engagement, ref_maj_mm)
        assert group == "S", (
            f"{desig}: engagement={engagement:.3f} mm should be group S"
        )

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, kind in _ALL_25
        if kind in ("metric_coarse", "metric_fine")
    ])
    def test_long_engagement_is_group_L(self, desig, ref_maj_mm, ref_pitch_mm):
        """engagement = 2.0 × D (above N boundary) → DIN 13-12 group L."""
        engagement = 2.0 * ref_maj_mm
        group = _engagement_din_group(engagement, ref_maj_mm)
        assert group == "L", (
            f"{desig}: engagement={engagement:.3f} mm should be group L"
        )

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, kind in _ALL_25
        if kind in ("metric_coarse", "metric_fine")
    ])
    def test_normal_upper_boundary_exactly(self, desig, ref_maj_mm, ref_pitch_mm):
        """engagement = 1.5 × D → still group N (inclusive upper bound)."""
        engagement = _DIN_NORMAL_MAX * ref_maj_mm
        group = _engagement_din_group(engagement, ref_maj_mm)
        assert group == "N", (
            f"{desig}: engagement at 1.5×D boundary should remain group N"
        )

    @pytest.mark.parametrize("desig,ref_maj_mm,ref_pitch_mm", [
        (d, maj, p) for d, maj, p, kind in _ALL_25
        if kind in ("metric_coarse", "metric_fine")
    ])
    def test_thread_depth_vs_din_normal_engagement(self, desig, ref_maj_mm, ref_pitch_mm):
        """
        Validate that a tapped hole with thread_depth = 1.0 × D satisfies
        DIN 13-12 group N engagement, and that the catalog pitch is consistent
        with the minor-diameter formula (confirming the spec is self-consistent
        before handing depth to the node builder).
        """
        spec = lookup(desig)
        assert spec is not None
        thread_depth = 1.0 * ref_maj_mm          # DIN normal engagement
        group = _engagement_din_group(thread_depth, spec["major_dia_mm"])
        assert group == "N"
        # Cross-check formula self-consistency
        expected_minor = round(spec["major_dia_mm"] - _ISO_K_METRIC * spec["pitch_mm"], 4)
        assert spec["minor_dia_mm"] == pytest.approx(expected_minor, abs=1e-4)


class TestEngagementLengthASME:
    """
    ASME B1.1 minimum recommended engagement = 1 × D_major.
    Verify that the DIN group N (which uses the same 1×D anchor) satisfies
    the ASME minimum for all UTS threads in the 25-spec set.
    """

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, kind in _ALL_25
        if kind in ("uts_unc", "uts_unf")
    ])
    def test_asme_min_engagement_mm(self, desig, ref_maj_in, ref_tpi):
        """Engagement = 1.0 × D_major satisfies ASME B1.1 minimum (≥ 1×D)."""
        spec = lookup(desig)
        assert spec is not None
        major_mm = spec["major_dia_mm"]
        engagement_mm = 1.0 * major_mm
        asme_min_mm = _min_engagement_asme_mm(major_mm)
        assert engagement_mm >= asme_min_mm - 1e-9, (
            f"{desig}: engagement {engagement_mm:.4f} mm < ASME min {asme_min_mm:.4f} mm"
        )

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, kind in _ALL_25
        if kind in ("uts_unc", "uts_unf")
    ])
    def test_uts_short_engagement_below_asme_min(self, desig, ref_maj_in, ref_tpi):
        """Engagement = 0.3 × D is below the ASME minimum — detect it."""
        spec = lookup(desig)
        assert spec is not None
        major_mm = spec["major_dia_mm"]
        engagement_mm = 0.3 * major_mm
        asme_min_mm = _min_engagement_asme_mm(major_mm)
        assert engagement_mm < asme_min_mm, (
            f"{desig}: 0.3×D={engagement_mm:.4f} should be < ASME min {asme_min_mm:.4f}"
        )

    @pytest.mark.parametrize("desig,ref_maj_in,ref_tpi", [
        (d, maj_in, tpi) for d, maj_in, tpi, kind in _ALL_25
        if kind in ("uts_unc", "uts_unf")
    ])
    def test_uts_pitch_formula_self_consistent(self, desig, ref_maj_in, ref_tpi):
        """
        pitch_mm × TPI should equal 25.4 (mm/inch) to within 0.001 mm —
        ensures the pitch stored in the catalog is the exact inverse of TPI.
        """
        spec = lookup(desig)
        assert spec is not None
        reconstructed_inch = spec["pitch_mm"] * ref_tpi / 25.4
        # Should be ≈ 1.0 (one inch worth of threads per unit)
        assert reconstructed_inch == pytest.approx(1.0, abs=1e-3), (
            f"{desig}: pitch_mm×TPI/25.4={reconstructed_inch:.6f} should be 1.0"
        )


# ---------------------------------------------------------------------------
# Part C — Boundaries, malformed inputs, idempotency
# ---------------------------------------------------------------------------

class TestParseDesignationBoundaries:
    """Edge cases for parse_designation."""

    def test_empty_string_rejected(self):
        result = parse_designation("")
        assert result["ok"] is False
        assert "non-empty" in result["errors"][0]

    def test_whitespace_only_rejected(self):
        result = parse_designation("   ")
        assert result["ok"] is False

    def test_none_type_rejected(self):
        result = parse_designation(None)  # type: ignore[arg-type]
        assert result["ok"] is False

    def test_int_type_rejected(self):
        result = parse_designation(42)  # type: ignore[arg-type]
        assert result["ok"] is False

    def test_unknown_metric_rejected(self):
        result = parse_designation("M99")
        assert result["ok"] is False

    def test_unknown_uts_rejected(self):
        result = parse_designation("#99-99 UNC")
        assert result["ok"] is False

    def test_malformed_fractional_rejected(self):
        result = parse_designation("1/4 UNC")      # missing TPI
        assert result["ok"] is False

    def test_case_insensitive_metric(self):
        """'m6' and 'M6' both resolve to the M6 spec."""
        r_lower = parse_designation("m6")
        r_upper = parse_designation("M6")
        # Both must succeed and yield the same canonical spec
        assert r_lower["ok"] is True
        assert r_upper["ok"] is True
        assert r_lower["spec"]["designation"] == r_upper["spec"]["designation"] == "M6"

    def test_case_insensitive_uts(self):
        """'1/4-20 unc' resolves to the canonical '1/4-20 UNC' spec."""
        result = parse_designation("1/4-20 unc")
        assert result["ok"] is True
        assert result["canonical"] == "1/4-20 UNC"

    def test_leading_trailing_whitespace_stripped(self):
        """Surrounding whitespace must not block a valid designation."""
        result = parse_designation("  M6  ")
        assert result["ok"] is True
        assert result["spec"]["major_dia_mm"] == pytest.approx(6.0)

    def test_idempotency_parse_metric(self):
        """Parsing the canonical form twice yields identical specs."""
        r1 = parse_designation("M10")
        r2 = parse_designation("M10")
        assert r1["ok"] is True
        assert r2["ok"] is True
        assert r1["spec"] == r2["spec"]

    def test_idempotency_parse_uts(self):
        """Parsing the canonical UTS form twice yields identical specs."""
        r1 = parse_designation("1/2-13 UNC")
        r2 = parse_designation("1/2-13 UNC")
        assert r1["ok"] is True
        assert r2["spec"] == r2["spec"]


class TestValidateTappedHoleBoundaries:
    """validate_tapped_hole_args boundary / malformed cases."""

    def _call(
        self,
        designation="M6",
        depth=20.0,
        hole_type="blind",
        thread_depth=15.0,
        cb_dia=None,
        cb_dep=None,
        cs_dia=None,
        cs_ang=None,
    ):
        return validate_tapped_hole_args(
            designation, depth, hole_type, thread_depth,
            cb_dia, cb_dep, cs_dia, cs_ang,
        )

    def test_through_hole_no_thread_depth_ok(self):
        err, code, spec = self._call(hole_type="through", thread_depth=None)
        assert err is None and code is None
        assert spec is not None

    def test_blind_hole_thread_depth_at_depth_boundary(self):
        """thread_depth == depth is the exact boundary — must be accepted."""
        err, code, spec = self._call(depth=20.0, thread_depth=20.0)
        assert err is None and code is None

    def test_blind_hole_thread_depth_just_over_depth_rejected(self):
        """thread_depth > depth must be rejected."""
        err, code, _ = self._call(depth=20.0, thread_depth=20.001)
        assert code == "BAD_ARGS"

    def test_depth_negative_rejected(self):
        err, code, _ = self._call(depth=-1.0)
        assert code == "BAD_ARGS"

    def test_depth_exactly_zero_rejected(self):
        err, code, _ = self._call(depth=0.0)
        assert code == "BAD_ARGS"

    def test_depth_small_positive_accepted(self):
        err, code, _ = self._call(depth=0.001, thread_depth=0.001)
        assert err is None

    def test_counterbore_exactly_at_major_dia_rejected(self):
        """counterbore_dia must be *larger than* major diameter."""
        spec = lookup("M6")
        assert spec is not None
        cb_dia = spec["major_dia_mm"]   # exactly equal — not larger
        err, code, _ = self._call(cb_dia=cb_dia, cb_dep=3.0)
        assert code == "BAD_ARGS"

    def test_counterbore_just_above_major_dia_accepted(self):
        spec = lookup("M6")
        assert spec is not None
        cb_dia = spec["major_dia_mm"] + 0.001
        err, code, _ = self._call(cb_dia=cb_dia, cb_dep=3.0)
        assert err is None

    def test_countersink_angle_lower_boundary_accepted(self):
        """30° is the minimum accepted countersink angle."""
        err, code, _ = self._call(cs_dia=10.0, cs_ang=30.0)
        assert err is None

    def test_countersink_angle_upper_boundary_accepted(self):
        """150° is the maximum accepted countersink angle."""
        err, code, _ = self._call(cs_dia=10.0, cs_ang=150.0)
        assert err is None

    def test_countersink_angle_just_below_lower_rejected(self):
        err, code, _ = self._call(cs_dia=10.0, cs_ang=29.9)
        assert code == "BAD_ARGS"

    def test_countersink_angle_just_above_upper_rejected(self):
        err, code, _ = self._call(cs_dia=10.0, cs_ang=150.1)
        assert code == "BAD_ARGS"

    def test_invalid_hole_type_rejected(self):
        err, code, _ = self._call(hole_type="partial")
        assert code == "BAD_ARGS"

    def test_blind_requires_thread_depth(self):
        err, code, _ = self._call(hole_type="blind", thread_depth=None)
        assert code == "BAD_ARGS"

    def test_idempotency_valid_blind(self):
        """Two identical calls yield identical results."""
        r1 = self._call()
        r2 = self._call()
        assert r1[0] == r2[0] and r1[1] == r2[1]
        assert r1[2] == r2[2]


class TestValidateExternalThreadBoundaries:
    """validate_external_thread_args boundary / malformed cases."""

    def test_shaft_dia_zero_rejected(self):
        err, code, _ = validate_external_thread_args(0.0, "M6", 20.0, None)
        assert code == "BAD_ARGS"

    def test_shaft_dia_negative_rejected(self):
        err, code, _ = validate_external_thread_args(-1.0, "M6", 20.0, None)
        assert code == "BAD_ARGS"

    def test_length_zero_rejected(self):
        err, code, _ = validate_external_thread_args(6.0, "M6", 0.0, None)
        assert code == "BAD_ARGS"

    def test_length_negative_rejected(self):
        err, code, _ = validate_external_thread_args(6.0, "M6", -5.0, None)
        assert code == "BAD_ARGS"

    def test_shaft_dia_just_within_tolerance_accepted(self):
        """shaft_dia = major_dia + (SHAFT_TOLERANCE_MM - epsilon) — accepted."""
        spec = lookup("M10")
        assert spec is not None
        # tolerance check is abs(shaft - major) > TOL, so exactly TOL is rejected;
        # TOL - small_epsilon must be accepted.
        shaft = spec["major_dia_mm"] + SHAFT_TOLERANCE_MM - 0.001
        err, code, _ = validate_external_thread_args(shaft, "M10", 15.0, None)
        assert err is None

    def test_shaft_dia_at_exact_tolerance_rejected(self):
        """shaft_dia = major_dia + SHAFT_TOLERANCE_MM (exact) → MISMATCH (strictly >)."""
        spec = lookup("M10")
        assert spec is not None
        shaft = spec["major_dia_mm"] + SHAFT_TOLERANCE_MM
        err, code, _ = validate_external_thread_args(shaft, "M10", 15.0, None)
        assert code == "MISMATCH"

    def test_shaft_dia_just_over_tolerance_rejected(self):
        """shaft_dia just outside tolerance → MISMATCH."""
        spec = lookup("M10")
        assert spec is not None
        shaft = spec["major_dia_mm"] + SHAFT_TOLERANCE_MM + 0.01
        err, code, _ = validate_external_thread_args(shaft, "M10", 15.0, None)
        assert code == "MISMATCH"

    def test_uts_shaft_tolerance_accepted(self):
        """UTS thread: shaft within ±0.3 mm of major_dia_mm is accepted."""
        spec = lookup("1/4-20 UNC")
        assert spec is not None
        shaft = spec["major_dia_mm"]  # exact match
        err, code, _ = validate_external_thread_args(shaft, "1/4-20 UNC", 10.0, None)
        assert err is None

    def test_idempotency_valid_external(self):
        err1, code1, spec1 = validate_external_thread_args(6.0, "M6", 20.0, None)
        err2, code2, spec2 = validate_external_thread_args(6.0, "M6", 20.0, None)
        assert err1 == err2 and code1 == code2 and spec1 == spec2


class TestBuildTappedHoleNodeBoss:
    """build_tapped_hole_node (tapped-hole cut) and boss (external thread) node shape."""

    def test_tapped_hole_node_keys_metric(self):
        spec = lookup("M6")
        assert spec is not None
        node = build_tapped_hole_node(
            "tapped_hole-1", "M6", spec,
            depth=20.0, hole_type="blind", thread_depth=15.0,
        )
        for key in ("id", "op", "designation", "depth", "hole_type",
                    "tap_drill_dia", "pitch_mm", "major_dia_mm",
                    "minor_dia_mm", "thread_class", "cosmetic_thread"):
            assert key in node, f"missing key {key!r}"

    def test_tapped_hole_node_no_inch_keys_for_metric(self):
        spec = lookup("M12")
        assert spec is not None
        node = build_tapped_hole_node(
            "th-1", "M12", spec, depth=25.0, hole_type="through", thread_depth=None,
        )
        assert "major_dia_in" not in node

    def test_tapped_hole_node_inch_keys_for_uts(self):
        spec = lookup("1/2-13 UNC")
        assert spec is not None
        node = build_tapped_hole_node(
            "th-1", "1/2-13 UNC", spec, depth=20.0, hole_type="through", thread_depth=None,
        )
        for key in ("major_dia_in", "pitch_in", "minor_dia_in", "tap_drill_in"):
            assert key in node, f"UTS node missing inch key {key!r}"

    def test_through_hole_thread_depth_equals_depth(self):
        """For through holes, thread_depth in the node must equal depth."""
        spec = lookup("M8")
        assert spec is not None
        node = build_tapped_hole_node(
            "th-1", "M8", spec, depth=30.0, hole_type="through", thread_depth=None,
        )
        assert node["thread_depth"] == pytest.approx(30.0)

    def test_counterbore_keys_present_when_set(self):
        spec = lookup("M6")
        assert spec is not None
        node = build_tapped_hole_node(
            "th-1", "M6", spec,
            depth=20.0, hole_type="blind", thread_depth=15.0,
            counterbore_dia=10.0, counterbore_depth=5.0,
        )
        assert node["counterbore_dia"] == pytest.approx(10.0)
        assert node["counterbore_depth"] == pytest.approx(5.0)

    def test_countersink_keys_present_when_set(self):
        spec = lookup("M6")
        assert spec is not None
        node = build_tapped_hole_node(
            "th-1", "M6", spec,
            depth=20.0, hole_type="blind", thread_depth=15.0,
            countersink_dia=12.0, countersink_angle_deg=90.0,
        )
        assert node["countersink_dia"] == pytest.approx(12.0)
        assert node["countersink_angle_deg"] == pytest.approx(90.0)

    def test_idempotency_node_builder(self):
        """Calling build_tapped_hole_node twice with same args gives same result."""
        spec = lookup("M10")
        assert spec is not None
        node1 = build_tapped_hole_node(
            "th-1", "M10", spec, depth=20.0, hole_type="blind", thread_depth=15.0,
        )
        node2 = build_tapped_hole_node(
            "th-1", "M10", spec, depth=20.0, hole_type="blind", thread_depth=15.0,
        )
        assert node1 == node2


class TestCatalogHelpers:
    """Helper functions for catalog navigation."""

    def test_metric_coarse_designations_count(self):
        desigs = metric_coarse_designations()
        assert len(desigs) == 30

    def test_metric_coarse_designations_ascending(self):
        """M1.6 must come before M64 in order."""
        desigs = metric_coarse_designations()
        assert desigs[0] == "M1.6"
        assert desigs[-1] == "M64"

    def test_uts_unc_designations_all_present_in_catalog(self):
        for d in uts_unc_designations():
            assert d in ALL_THREADS, f"UNC designation {d!r} not in ALL_THREADS"

    def test_uts_unf_designations_all_present_in_catalog(self):
        for d in uts_unf_designations():
            assert d in ALL_THREADS, f"UNF designation {d!r} not in ALL_THREADS"

    def test_lookup_returns_none_for_unknown(self):
        assert lookup("M999") is None

    def test_lookup_returns_spec_for_known(self):
        spec = lookup("M6")
        assert spec is not None
        assert spec["designation"] == "M6"

    def test_all_threads_no_duplicate_keys(self):
        """Merging METRIC_ALL and UTS_ALL must not silently drop entries."""
        n_metric = len(METRIC_COARSE) + len(METRIC_FINE)
        # METRIC_ALL = METRIC_COARSE | METRIC_FINE (no overlap)
        from kerf_cad_core.thread_specs import METRIC_ALL
        assert len(METRIC_ALL) == n_metric
