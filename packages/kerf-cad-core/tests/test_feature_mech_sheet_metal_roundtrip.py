"""
T-17: Mech — sheet-metal flange → unfold round-trip.

Scope: sheet_metal.py flange (T-1) ⇒ unfold (T-2/T-3) ⇒ flat pattern.

Success criteria (from docs/plans/testing-breakdown.md T-17):
  • 25 part shapes exercised
  • Folded surface area ≈ unfolded area within k-factor tolerance
  • Bend allowance correct vs DIN 6935 formula
  • flange→unfold→refold preserves dimensions (round-trip oracle)
  • Boundary / malformed input coverage

No database, no OCCT, no ProjectCtx required.
The folded "area" is computed analytically from the geometry contract:
    base_area    = base_width × base_depth
    flange_area  = flange_length × base_width   (top-front / top-back bend)
    bend_arc_area= BA × base_width               (arc strip neutral-axis length × width)
    total_folded_area ≈ flat_pattern_area = developed_length × base_width

DIN 6935 BA formula: BA = (π/180)·angle_deg·(r + K·t)
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.sheet_metal import compute_unfold


# ---------------------------------------------------------------------------
# Reference oracle (DIN 6935)
# ---------------------------------------------------------------------------

def _din6935_ba(angle_deg: float, r: float, k: float, t: float) -> float:
    """BA = (π/180)·angle·(r + K·t)  — DIN 6935 neutral-axis formula."""
    return math.radians(angle_deg) * (r + k * t)


def _flat_area(base_length: float, flange_length: float, ba: float, width: float) -> float:
    """Total flat-pattern area = (base_length + BA + flange_length) × width."""
    return (base_length + ba + flange_length) * width


# ---------------------------------------------------------------------------
# 25 part shapes: (base_length, flange_length, angle_deg, r, t, k_factor, width)
# ---------------------------------------------------------------------------

PARTS = [
    # (base_length, flange_length, angle_deg, r,    t,    k,    width) description
    (50.0,  25.0,  90.0,  2.0,  1.5,  0.44,  100.0),   # 1  typical mild-steel 90°
    (80.0,  30.0,  90.0,  3.0,  2.0,  0.44,  120.0),   # 2  thicker plate
    (40.0,  20.0,  45.0,  1.5,  1.0,  0.33,   80.0),   # 3  hard steel 45°
    (60.0,  40.0, 135.0,  4.0,  2.5,  0.50,   90.0),   # 4  aluminium obtuse
    (100.0, 50.0, 180.0,  5.0,  3.0,  0.44,  150.0),   # 5  full 180° hem
    (30.0,  15.0,  60.0,  1.0,  0.8,  0.38,   60.0),   # 6  stainless thin
    (70.0,  35.0,  90.0,  2.5,  1.2,  0.44,  110.0),   # 7  standard L-bracket
    (25.0,  10.0,  30.0,  0.5,  0.5,  0.33,   50.0),   # 8  very shallow bend
    (90.0,  45.0, 120.0,  6.0,  3.5,  0.50,  130.0),   # 9  aluminium 120°
    (55.0,  28.0,  90.0,  2.0,  1.5,  0.44,   95.0),   # 10 near-typical
    (110.0, 55.0,  90.0,  3.0,  2.0,  0.33,  160.0),   # 11 large hard-steel
    (20.0,   8.0, 150.0,  1.0,  0.6,  0.50,   40.0),   # 12 small 150° return
    (75.0,  38.0,  75.0,  2.5,  1.8,  0.44,  105.0),   # 13 non-standard angle
    (45.0,  22.0,  90.0,  1.5,  1.0,  0.44,   70.0),   # 14 small L
    (65.0,  32.0, 105.0,  3.5,  2.2,  0.46,  100.0),   # 15 brass 105°
    (85.0,  42.0,  90.0,  4.0,  2.8,  0.50,  125.0),   # 16 thick aluminium
    (35.0,  18.0,  60.0,  1.2,  0.9,  0.38,   65.0),   # 17 stainless 60°
    (120.0, 60.0,  90.0,  5.0,  3.0,  0.44,  175.0),   # 18 large panel
    (50.0,  25.0,  90.0,  2.0,  1.5,  0.50,  100.0),   # 19 same dims, alu k
    (50.0,  25.0,  90.0,  2.0,  1.5,  0.33,  100.0),   # 20 same dims, hard k
    (50.0,  25.0,  45.0,  2.0,  1.5,  0.44,  100.0),   # 21 same dims, 45°
    (50.0,  25.0, 135.0,  2.0,  1.5,  0.44,  100.0),   # 22 same dims, 135°
    (200.0, 100.0, 90.0,  8.0,  5.0,  0.44,  300.0),   # 23 very large
    ( 5.0,   3.0,  90.0,  0.3,  0.3,  0.44,   10.0),   # 24 very small
    (15.0,   7.0, 170.0,  1.0,  0.8,  0.44,   30.0),   # 25 near-hem
]

assert len(PARTS) == 25, f"Expected 25 parts, got {len(PARTS)}"


# ===========================================================================
# 1. DIN 6935 bend-allowance formula match (25 parts)
# ===========================================================================

class TestDin6935BendAllowance:
    """compute_unfold BA must match the DIN 6935 reference formula exactly."""

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_ba_matches_din6935(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        expected_ba = _din6935_ba(angle_deg, r, k, t)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-4, (
            f"BA mismatch: got {result['bend_allowance']:.6f}, "
            f"expected {expected_ba:.6f}"
        )


# ===========================================================================
# 2. Folded area ≈ unfolded (flat) area within k-factor tolerance (25 parts)
#
# Area conservation:
#   Folded area  = base_length×width + arc_strip×width + flange_length×width
#               = (base_length + BA + flange_length) × width
#   Flat area    = developed_length × width
#
# Both equal (base_length + BA + flange_length) × width by construction,
# so the oracle is exact — but we also verify that the tolerance is tighter
# than 1 % of total area (DIN 6935 sheet-metal shop tolerance).
# ===========================================================================

class TestAreaConservation:
    """Flat-pattern area must equal the unrolled folded area."""

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_area_conserved(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        ba = result["bend_allowance"]
        dl = result["developed_length"]

        # Flat pattern area
        flat_area = dl * width

        # Analytic folded area (neutral-axis surface): same as flat by definition
        analytic_area = _flat_area(base_length, flange_length, ba, width)

        # Must agree to within 1% of flat area (DIN 6935 tolerance)
        tol = 0.01 * flat_area
        assert abs(flat_area - analytic_area) < tol, (
            f"Area mismatch: flat={flat_area:.4f}, analytic={analytic_area:.4f}"
        )

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_area_exact_match(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        """Flat area = (base + BA + flange) × width — exact to floating-point precision."""
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        dl = result["developed_length"]
        flat_area = dl * width
        ba = result["bend_allowance"]
        expected_area = (base_length + ba + flange_length) * width
        assert abs(flat_area - expected_area) < 1e-3, (
            f"Flat area {flat_area:.6f} ≠ expected {expected_area:.6f}"
        )


# ===========================================================================
# 3. Round-trip oracle: flange → unfold → refold (25 parts)
#
# Oracle:
#   Given (base_length, flange_length, k, ...) produce developed_length (flat).
#   Refold: we can reconstruct flange_length from developed_length and ba:
#     flange_reconstructed = developed_length − base_length − BA
#   This must equal the original flange_length to within 1e-4 mm.
#
#   Also: bend_lines[bend-end].position + flange_reconstructed = developed_length.
# ===========================================================================

class TestRoundTrip:
    """Flange → unfold → refold preserves all dimensions."""

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_flange_length_roundtrip(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        """Recover flange_length from (developed_length − base_length − BA)."""
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        ba = result["bend_allowance"]
        dl = result["developed_length"]

        flange_reconstructed = dl - base_length - ba
        assert abs(flange_reconstructed - flange_length) < 1e-4, (
            f"Flange round-trip: got {flange_reconstructed:.6f}, "
            f"expected {flange_length:.6f}"
        )

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_base_length_roundtrip(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        """bend-start position == base_length (the unfold knows where the bend begins)."""
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        bend_start = next(
            bl["position"] for bl in result["bend_lines"] if bl["label"] == "bend-start"
        )
        assert abs(bend_start - base_length) < 1e-6

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_developed_length_additivity(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        """developed_length = base_length + BA + flange_length (strict additivity)."""
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        ba = result["bend_allowance"]
        dl = result["developed_length"]
        expected = base_length + ba + flange_length
        assert abs(dl - expected) < 1e-4

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_bend_end_position(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        """bend-end = base_length + BA."""
        result = compute_unfold(base_length, flange_length, angle_deg, r, t, k)
        ba = result["bend_allowance"]
        bend_end = next(
            bl["position"] for bl in result["bend_lines"] if bl["label"] == "bend-end"
        )
        assert abs(bend_end - (base_length + ba)) < 1e-6

    @pytest.mark.parametrize(
        "base_length,flange_length,angle_deg,r,t,k,width",
        PARTS,
        ids=[f"part{i+1}" for i in range(25)],
    )
    def test_k_factor_effect_on_developed_length(
        self, base_length, flange_length, angle_deg, r, t, k, width
    ):
        """Higher k_factor → larger BA → larger developed_length (neutral axis farther out)."""
        k_lo = max(0.05, k - 0.05)
        k_hi = min(0.95, k + 0.05)
        if abs(k_hi - k_lo) < 1e-9:
            pytest.skip("k window collapsed at boundary")

        r_lo = compute_unfold(base_length, flange_length, angle_deg, r, t, k_lo)
        r_hi = compute_unfold(base_length, flange_length, angle_deg, r, t, k_hi)
        assert r_hi["developed_length"] > r_lo["developed_length"]


# ===========================================================================
# 4. Boundary / malformed inputs
# ===========================================================================

class TestBoundaryInputs:

    def test_angle_180_ba_double_of_90(self):
        """BA at 180° == 2 × BA at 90° for same r/t/k (scaling linearity)."""
        r90 = compute_unfold(50.0, 25.0, 90.0, 2.0, 1.5, 0.44)
        r180 = compute_unfold(50.0, 25.0, 180.0, 2.0, 1.5, 0.44)
        assert abs(r180["bend_allowance"] - 2 * r90["bend_allowance"]) < 1e-6

    def test_angle_1_deg_ba_positive(self):
        """Even a 1° bend must produce a positive, non-zero BA."""
        result = compute_unfold(50.0, 25.0, 1.0, 2.0, 1.5, 0.44)
        assert result["bend_allowance"] > 0

    def test_very_thin_sheet(self):
        """t=0.1 mm (thin foil) still produces a sane BA."""
        result = compute_unfold(50.0, 25.0, 90.0, 0.5, 0.1, 0.44)
        expected_ba = _din6935_ba(90.0, 0.5, 0.44, 0.1)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-5

    def test_very_large_radius(self):
        """Large radius produces proportionally large BA."""
        r_small = compute_unfold(50.0, 25.0, 90.0, 1.0, 1.5, 0.44)
        r_large = compute_unfold(50.0, 25.0, 90.0, 100.0, 1.5, 0.44)
        assert r_large["bend_allowance"] > r_small["bend_allowance"] * 10

    def test_k_factor_boundary_low(self):
        """k_factor=0.01 (near zero) returns a valid, smaller BA than k=0.44."""
        r_low  = compute_unfold(50.0, 25.0, 90.0, 2.0, 1.5, 0.01)
        r_mid  = compute_unfold(50.0, 25.0, 90.0, 2.0, 1.5, 0.44)
        assert r_low["bend_allowance"] < r_mid["bend_allowance"]

    def test_k_factor_boundary_high(self):
        """k_factor=0.99 (near one) returns valid result with large BA."""
        r_hi = compute_unfold(50.0, 25.0, 90.0, 2.0, 1.5, 0.99)
        expected_ba = _din6935_ba(90.0, 2.0, 0.99, 1.5)
        assert abs(r_hi["bend_allowance"] - expected_ba) < 1e-4

    def test_zero_base_raises_no_exception(self):
        """compute_unfold is a pure math function; it does not validate inputs.
        The runner (run_sheet_metal_unfold) performs validation.
        A zero base_length simply shifts all bend-line positions to 0."""
        result = compute_unfold(0.0, 25.0, 90.0, 2.0, 1.5, 0.44)
        assert result["developed_length"] == pytest.approx(
            _din6935_ba(90.0, 2.0, 0.44, 1.5) + 25.0, abs=1e-4
        )

    def test_bend_lines_always_two(self):
        """compute_unfold always returns exactly two bend-line entries."""
        for angle in [1.0, 45.0, 90.0, 135.0, 180.0]:
            result = compute_unfold(50.0, 25.0, angle, 2.0, 1.5, 0.44)
            assert len(result["bend_lines"]) == 2

    def test_bend_line_labels_present(self):
        labels = {bl["label"] for bl in compute_unfold(50, 25, 90, 2, 1.5, 0.44)["bend_lines"]}
        assert labels == {"bend-start", "bend-end"}

    def test_bend_start_lt_bend_end(self):
        """bend-start must always be before bend-end on the developed strip."""
        for angle in [15.0, 45.0, 90.0, 120.0, 170.0]:
            result = compute_unfold(50.0, 25.0, angle, 2.0, 1.5, 0.44)
            pos_start = next(bl["position"] for bl in result["bend_lines"] if bl["label"] == "bend-start")
            pos_end   = next(bl["position"] for bl in result["bend_lines"] if bl["label"] == "bend-end")
            assert pos_start < pos_end, f"bend-start not < bend-end at angle={angle}"

    def test_developed_length_gt_sum_of_legs(self):
        """developed_length must always be strictly > base + flange (BA > 0)."""
        for r, t, k in [(0.5, 0.5, 0.33), (2.0, 1.5, 0.44), (5.0, 3.0, 0.50)]:
            result = compute_unfold(50.0, 25.0, 90.0, r, t, k)
            assert result["developed_length"] > 75.0


# ===========================================================================
# 5. DIN 6935 cross-check against hand-calc reference values
# ===========================================================================

class TestDin6935HandCalc:
    """Spot-check specific values from the DIN 6935 / Machinery's Handbook."""

    def test_mild_steel_90deg_r2_t15_k044(self):
        """
        BA = (π/2) × (2.0 + 0.44 × 1.5) = (π/2) × 2.66 ≈ 4.17699…
        Developed length for base=50, flange=25: 50 + 4.17699 + 25 = 79.17699
        """
        result = compute_unfold(50.0, 25.0, 90.0, 2.0, 1.5, 0.44)
        expected_ba = (math.pi / 2) * (2.0 + 0.44 * 1.5)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-5
        assert abs(result["developed_length"] - (50.0 + expected_ba + 25.0)) < 1e-4

    def test_aluminium_90deg_r3_t2_k050(self):
        """
        BA = (π/2) × (3.0 + 0.50 × 2.0) = (π/2) × 4.0 = 2π ≈ 6.28318…
        """
        result = compute_unfold(60.0, 30.0, 90.0, 3.0, 2.0, 0.50)
        expected_ba = (math.pi / 2) * 4.0
        assert abs(result["bend_allowance"] - expected_ba) < 1e-5

    def test_stainless_90deg_r2_t1_k038(self):
        """
        BA = (π/2) × (2.0 + 0.38 × 1.0) = (π/2) × 2.38 ≈ 3.73..
        """
        result = compute_unfold(40.0, 20.0, 90.0, 2.0, 1.0, 0.38)
        expected_ba = (math.pi / 2) * (2.0 + 0.38 * 1.0)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-5

    def test_hard_steel_45deg_r1_t1_k033(self):
        """
        BA = (π/4) × (1.0 + 0.33 × 1.0) = (π/4) × 1.33 ≈ 1.04453…
        """
        result = compute_unfold(30.0, 15.0, 45.0, 1.0, 1.0, 0.33)
        expected_ba = math.radians(45) * (1.0 + 0.33 * 1.0)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-5

    def test_180deg_hem_r1_t1_k044(self):
        """
        BA = π × (1.0 + 0.44 × 1.0) = π × 1.44 ≈ 4.52389…
        """
        result = compute_unfold(50.0, 10.0, 180.0, 1.0, 1.0, 0.44)
        expected_ba = math.pi * (1.0 + 0.44 * 1.0)
        assert abs(result["bend_allowance"] - expected_ba) < 1e-5

    def test_angle_proportional_to_ba(self):
        """BA must scale linearly with bend angle (same r/t/k)."""
        r30  = compute_unfold(50.0, 25.0,  30.0, 2.0, 1.5, 0.44)
        r60  = compute_unfold(50.0, 25.0,  60.0, 2.0, 1.5, 0.44)
        r90  = compute_unfold(50.0, 25.0,  90.0, 2.0, 1.5, 0.44)
        r180 = compute_unfold(50.0, 25.0, 180.0, 2.0, 1.5, 0.44)
        ba_30 = r30["bend_allowance"]
        ba_60 = r60["bend_allowance"]
        ba_90 = r90["bend_allowance"]
        ba_180 = r180["bend_allowance"]

        # Tolerance of 1e-5 accommodates the round(..., 6) in compute_unfold.
        assert abs(ba_60 - 2 * ba_30) < 1e-5
        assert abs(ba_90 - 3 * ba_30) < 1e-5
        assert abs(ba_180 - 6 * ba_30) < 1e-5

    def test_radius_proportional_to_ba(self):
        """BA must scale linearly with (r + K×t) — doubling effective radius doubles BA."""
        r1 = compute_unfold(50.0, 25.0, 90.0, 1.0, 0.0, 0.44)  # t≈0 → eff_r = r
        r2 = compute_unfold(50.0, 25.0, 90.0, 2.0, 0.0, 0.44)
        # t=0.0 is not validated by compute_unfold (pure math), so this works
        assert abs(r2["bend_allowance"] / r1["bend_allowance"] - 2.0) < 1e-5
