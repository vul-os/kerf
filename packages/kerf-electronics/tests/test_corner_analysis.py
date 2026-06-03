"""test_corner_analysis.py — Tests for PVT / Monte-Carlo corner analysis.

Coverage:
  - DEFAULT_CORNERS: names, signs, count
  - ProcessCorner.apply: parameter deltas correctly applied
  - PvtSweepSpec defaults
  - run_pvt_corner_sweep: row count, fields, yield_estimate, worst_id_pct
  - corner_summary: per-corner stats, honest_disclaimer
  - Determinism: same seed → same result
  - Yield with impossible spec → 0
  - Box-Muller RNG: Gaussian properties
"""

from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from kerf_electronics.spice.bsim4_model import Bsim4Geometry, Bsim4Parameters
from kerf_electronics.spice.corner_analysis import (
    DEFAULT_CORNERS,
    CornerSweepReport,
    ProcessCorner,
    PvtSweepSpec,
    _BoxMullerRng,
    corner_summary,
    run_pvt_corner_sweep,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def params():
    return Bsim4Parameters()


@pytest.fixture
def geom():
    return Bsim4Geometry(W=1e-6, L=100e-9)


@pytest.fixture
def default_spec():
    return PvtSweepSpec()


# ---------------------------------------------------------------------------
# 1. DEFAULT_CORNERS
# ---------------------------------------------------------------------------

class TestDefaultCorners:
    def test_five_corners(self):
        """DEFAULT_CORNERS should contain exactly 5 corners."""
        assert len(DEFAULT_CORNERS) == 5

    def test_corner_names(self):
        """Corner names should be TT, SS, FF, SF, FS."""
        names = {c.name for c in DEFAULT_CORNERS}
        assert names == {"TT", "SS", "FF", "SF", "FS"}

    def test_tt_is_nominal(self):
        """TT corner should have zero deltas."""
        tt = next(c for c in DEFAULT_CORNERS if c.name == "TT")
        assert tt.vth_delta_pct == 0.0
        assert tt.mobility_delta_pct == 0.0

    def test_ss_has_positive_vth_delta(self):
        """SS (slow-slow) should have positive Vth delta (higher Vth)."""
        ss = next(c for c in DEFAULT_CORNERS if c.name == "SS")
        assert ss.vth_delta_pct > 0.0

    def test_ss_has_negative_mobility_delta(self):
        """SS should have negative mobility delta (lower μ)."""
        ss = next(c for c in DEFAULT_CORNERS if c.name == "SS")
        assert ss.mobility_delta_pct < 0.0

    def test_ff_has_negative_vth_delta(self):
        """FF (fast-fast) should have negative Vth delta."""
        ff = next(c for c in DEFAULT_CORNERS if c.name == "FF")
        assert ff.vth_delta_pct < 0.0

    def test_ff_has_positive_mobility_delta(self):
        """FF should have positive mobility delta."""
        ff = next(c for c in DEFAULT_CORNERS if c.name == "FF")
        assert ff.mobility_delta_pct > 0.0

    def test_sf_signs(self):
        """SF: slow-Vth (positive), fast-β (positive)."""
        sf = next(c for c in DEFAULT_CORNERS if c.name == "SF")
        assert sf.vth_delta_pct > 0.0
        assert sf.mobility_delta_pct > 0.0

    def test_fs_signs(self):
        """FS: fast-Vth (negative), slow-β (negative)."""
        fs = next(c for c in DEFAULT_CORNERS if c.name == "FS")
        assert fs.vth_delta_pct < 0.0
        assert fs.mobility_delta_pct < 0.0


# ---------------------------------------------------------------------------
# 2. ProcessCorner.apply
# ---------------------------------------------------------------------------

class TestProcessCornerApply:
    def test_apply_tt_unchanged(self, params):
        """Applying TT corner should leave params unchanged."""
        tt  = ProcessCorner("TT", 0.0, 0.0)
        pp  = ProcessCorner.apply(tt, params)
        assert pp.vth0 == pytest.approx(params.vth0, rel=1e-9)
        assert pp.u0   == pytest.approx(params.u0,   rel=1e-9)

    def test_apply_ss_shifts_correctly(self, params):
        """SS corner should raise Vth and lower mobility by expected %."""
        ss = ProcessCorner("SS", 5.0, -5.0)
        pp = ProcessCorner.apply(ss, params)
        assert pp.vth0 == pytest.approx(params.vth0 * 1.05, rel=1e-9)
        assert pp.u0   == pytest.approx(params.u0   * 0.95, rel=1e-9)

    def test_apply_ff_shifts_correctly(self, params):
        """FF corner should lower Vth and raise mobility."""
        ff = ProcessCorner("FF", -5.0, 5.0)
        pp = ProcessCorner.apply(ff, params)
        assert pp.vth0 == pytest.approx(params.vth0 * 0.95, rel=1e-9)
        assert pp.u0   == pytest.approx(params.u0   * 1.05, rel=1e-9)

    def test_original_params_unchanged(self, params):
        """Applying a corner must not mutate the original params object."""
        original_vth0 = params.vth0
        ProcessCorner.apply(ProcessCorner("SS", 5.0, -5.0), params)
        assert params.vth0 == original_vth0


# ---------------------------------------------------------------------------
# 3. PvtSweepSpec defaults
# ---------------------------------------------------------------------------

class TestPvtSweepSpec:
    def test_default_voltages(self, default_spec):
        """Default voltages should be [0.9, 1.0, 1.1]."""
        assert default_spec.voltages_vdd == [0.9, 1.0, 1.1]

    def test_default_temperatures(self, default_spec):
        """Default temperatures should cover −40, 27, 125 °C."""
        assert -40.0 in default_spec.temperatures_c
        assert 27.0  in default_spec.temperatures_c
        assert 125.0 in default_spec.temperatures_c

    def test_default_mc_iterations(self, default_spec):
        """Default MC iterations should be 100."""
        assert default_spec.monte_carlo_iterations == 100

    def test_default_five_corners(self, default_spec):
        """Default spec should include 5 process corners."""
        assert len(default_spec.process_corners) == 5


# ---------------------------------------------------------------------------
# 4. run_pvt_corner_sweep: structure
# ---------------------------------------------------------------------------

class TestRunPvtCornerSweep:
    def test_sweep_row_count_default(self, params, geom):
        """Default spec: 5 corners × 3 voltages × 3 temperatures × 100 MC = 4500 rows."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        expected = 5 * 3 * 3 * 100
        assert len(report.sweeps) == expected

    def test_sweep_row_fields(self, params, geom):
        """Each sweep row should have required fields."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        row = report.sweeps[0]
        for field in ("corner", "vdd", "T_c", "mc_iter", "Id_A", "dvth_V", "dbeta"):
            assert field in row, f"Missing field: {field}"

    def test_yield_between_0_and_1(self, params, geom):
        """yield_estimate should always be in [0, 1]."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        assert 0.0 <= report.yield_estimate <= 1.0

    def test_yield_with_no_spec_is_one(self, params, geom):
        """Without spec_min_id, all samples pass → yield = 1.0."""
        report = run_pvt_corner_sweep(
            params, geom, vgs=1.0, vds=1.0, vbs=0.0, spec_min_id=None
        )
        assert report.yield_estimate == pytest.approx(1.0)

    def test_yield_with_impossible_spec_is_zero(self, params, geom):
        """An impossible spec (Id > 100A) should yield ≈ 0."""
        report = run_pvt_corner_sweep(
            params, geom, vgs=1.0, vds=1.0, vbs=0.0, spec_min_id=100.0
        )
        assert report.yield_estimate == pytest.approx(0.0)

    def test_worst_id_pct_nonnegative(self, params, geom):
        """worst_id_pct should be ≥ 0."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        assert report.worst_id_pct >= 0.0

    def test_worst_pvt_is_tuple_of_three(self, params, geom):
        """worst_pvt should be a (corner_name, vdd, T_c) tuple."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        assert len(report.worst_pvt) == 3

    def test_nominal_id_positive(self, params, geom):
        """Nominal Id should be positive for Vgs=Vds=1V."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        assert report.nominal_id > 0.0

    def test_ids_all_nonnegative(self, params, geom):
        """All Id values in sweep rows should be non-negative."""
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0)
        for row in report.sweeps:
            assert row["Id_A"] >= 0.0, f"Negative Id in row: {row}"

    def test_custom_mc_iterations(self, params, geom):
        """Custom MC count should be reflected in row count."""
        spec = PvtSweepSpec(monte_carlo_iterations=10)
        report = run_pvt_corner_sweep(params, geom, vgs=1.0, vds=1.0, vbs=0.0, spec=spec)
        expected = 5 * 3 * 3 * 10
        assert len(report.sweeps) == expected


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_same_seed_same_results(self, params, geom):
        """Same RNG seed should produce identical sweep results."""
        spec = PvtSweepSpec(monte_carlo_iterations=20)
        r1 = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0, spec, rng_seed=42)
        r2 = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0, spec, rng_seed=42)
        for row1, row2 in zip(r1.sweeps, r2.sweeps):
            assert row1["Id_A"]   == row2["Id_A"]
            assert row1["dvth_V"] == row2["dvth_V"]

    def test_different_seed_different_results(self, params, geom):
        """Different RNG seeds should (almost certainly) produce different results."""
        spec = PvtSweepSpec(monte_carlo_iterations=20)
        r1 = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0, spec, rng_seed=0)
        r2 = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0, spec, rng_seed=99)
        # At least one row should differ
        diffs = sum(1 for a, b in zip(r1.sweeps, r2.sweeps) if a["dvth_V"] != b["dvth_V"])
        assert diffs > 0


# ---------------------------------------------------------------------------
# 6. corner_summary
# ---------------------------------------------------------------------------

class TestCornerSummary:
    def test_summary_has_all_corners(self, params, geom):
        """summary per_corner_stats should contain all 5 corners."""
        report  = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0)
        summary = corner_summary(report)
        for name in ("TT", "SS", "FF", "SF", "FS"):
            assert name in summary["per_corner_stats"]

    def test_summary_has_honest_disclaimer(self, params, geom):
        """Summary should include an honest disclaimer."""
        report  = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0)
        summary = corner_summary(report)
        assert "honest_disclaimer" in summary
        assert len(summary["honest_disclaimer"]) > 10

    def test_summary_min_max_sane(self, params, geom):
        """Per-corner min_Id ≤ mean_Id ≤ max_Id."""
        report  = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0)
        summary = corner_summary(report)
        for cname, stats in summary["per_corner_stats"].items():
            assert stats["min_Id_A"] <= stats["mean_Id_A"] <= stats["max_Id_A"], cname

    def test_summary_yield_matches_report(self, params, geom):
        """Summary yield_estimate should match the CornerSweepReport value."""
        report  = run_pvt_corner_sweep(params, geom, 1.0, 1.0, 0.0)
        summary = corner_summary(report)
        assert summary["yield_estimate"] == pytest.approx(report.yield_estimate)


# ---------------------------------------------------------------------------
# 7. Box-Muller RNG internal
# ---------------------------------------------------------------------------

class TestBoxMullerRng:
    def test_gaussian_mean_close_to_zero(self):
        """Mean of many Gaussian samples should be close to 0."""
        rng = _BoxMullerRng(seed=123)
        samples = [rng.gauss(0.0, 1.0) for _ in range(1000)]
        mean = sum(samples) / len(samples)
        assert abs(mean) < 0.1, f"Mean {mean:.4f} too far from 0"

    def test_gaussian_std_close_to_one(self):
        """Std-dev of samples should be close to 1."""
        rng = _BoxMullerRng(seed=456)
        samples = [rng.gauss(0.0, 1.0) for _ in range(1000)]
        mean  = sum(samples) / len(samples)
        var   = sum((x - mean) ** 2 for x in samples) / len(samples)
        sigma = math.sqrt(var)
        assert 0.9 < sigma < 1.1, f"Std {sigma:.4f} out of [0.9, 1.1]"

    def test_deterministic(self):
        """Same seed produces same sequence."""
        rng1 = _BoxMullerRng(seed=7)
        rng2 = _BoxMullerRng(seed=7)
        vals1 = [rng1.gauss() for _ in range(20)]
        vals2 = [rng2.gauss() for _ in range(20)]
        assert vals1 == vals2
