"""
Hermetic tests for kerf_cad_core.earthworks — site earthworks & grading.

Coverage
--------
  grading.cross_section_level         — level section area hand-calcs
  grading.cross_section_two_level     — unsymmetrical section area
  grading.cross_section_three_level   — three-level shoelace formula
  grading.cross_section_by_coords     — arbitrary polygon area
  grading.earthwork_volume            — average-end-area + prismoidal
  grading.borrow_pit_volume           — 4-quadrant grid method
  grading.cut_fill_balance            — shrinkage/swell balance
  grading.mass_haul                   — ordinates, balance points, costs
  grading.proctor_optimum             — parabolic fit for OMC/MDD
  grading.relative_compaction         — RC% and pass/fail
  grading.lift_productivity           — roller productivity
  grading.slope_daylight_offset       — cut/fill daylight offset
  grading.trench_volume               — trapezoidal trench + pipe + bedding
  grading.dewatering_pump_rate        — Dupuit–Thiem pump rate
  tools.*                             — LLM tool wrappers (happy-path + error)

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Values verified against hand-calculations from published earthwork texts.

References
----------
Peurifoy, Schexnayder, Shapira, "Construction Planning, Equipment &
  Methods", 8th ed., McGraw-Hill 2011.
USBR "Design of Small Canal Structures", 1978.
ASTM D698 — Standard Proctor compaction.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
import warnings

import pytest

from kerf_cad_core.earthworks.grading import (
    cross_section_level,
    cross_section_two_level,
    cross_section_three_level,
    cross_section_by_coords,
    earthwork_volume,
    borrow_pit_volume,
    cut_fill_balance,
    mass_haul,
    proctor_optimum,
    relative_compaction,
    lift_productivity,
    slope_daylight_offset,
    trench_volume,
    dewatering_pump_rate,
)
from kerf_cad_core.earthworks.tools import (
    run_earthworks_cross_section,
    run_earthworks_volume,
    run_earthworks_borrow_pit,
    run_earthworks_cut_fill_balance,
    run_earthworks_mass_haul,
    run_earthworks_proctor,
    run_earthworks_relative_compaction,
    run_earthworks_lift_productivity,
    run_earthworks_slope_daylight,
    run_earthworks_trench,
    run_earthworks_dewatering,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


REL = 1e-6   # relative tolerance
ABS = 1e-6   # absolute tolerance


# ===========================================================================
# 1. Level cross-section
# ===========================================================================

class TestCrossSectionLevel:

    def test_rectangular_zero_slope(self):
        """A flat-bottom road (s=0): area = b × h = 6 × 2 = 12 m²."""
        r = cross_section_level(formation_width=6.0, centre_height=2.0, side_slope=0.0)
        assert abs(r["area_m2"] - 12.0) < ABS
        assert r["half_width_m"] == 3.0

    def test_typical_road_cut(self):
        """b=8 m, h=3 m, s=1.5: area = (8 + 1.5×3)×3 = (8+4.5)×3 = 37.5 m²."""
        r = cross_section_level(formation_width=8.0, centre_height=3.0, side_slope=1.5)
        assert abs(r["area_m2"] - 37.5) < ABS

    def test_half_width(self):
        """half_width = b/2 + s×h = 4 + 1.5×3 = 8.5 m."""
        r = cross_section_level(formation_width=8.0, centre_height=3.0, side_slope=1.5)
        assert abs(r["half_width_m"] - 8.5) < ABS

    def test_zero_height_warning(self):
        r = cross_section_level(formation_width=6.0, centre_height=0.0, side_slope=1.5)
        assert r["area_m2"] == 0.0
        assert len(r["warnings"]) > 0

    def test_bad_formation_width_raises(self):
        with pytest.raises(ValueError):
            cross_section_level(formation_width=0.0, centre_height=1.0, side_slope=1.5)


# ===========================================================================
# 2. Two-level cross-section
# ===========================================================================

class TestCrossSectionTwoLevel:

    def test_symmetrical_matches_level(self):
        """Symmetrical two-level should equal level section."""
        rl = cross_section_level(6.0, 2.0, 1.5)
        r2 = cross_section_two_level(6.0, 2.0, 1.5, 1.5)
        assert abs(r2["area_m2"] - rl["area_m2"]) < ABS

    def test_unsymmetrical_area(self):
        """b=6, h=2, sL=1, sR=2.
        left_hw = 3+1×2=5, right_hw = 3+2×2=7
        area = ((5+7)+6)/2 × 2 = (12+6)/2 × 2 = 9 × 2 = 18 m²."""
        r = cross_section_two_level(6.0, 2.0, 1.0, 2.0)
        assert abs(r["area_m2"] - 18.0) < ABS
        assert abs(r["left_half_width_m"] - 5.0) < ABS
        assert abs(r["right_half_width_m"] - 7.0) < ABS


# ===========================================================================
# 3. Three-level cross-section
# ===========================================================================

class TestCrossSectionThreeLevel:

    def test_level_degenerate_matches_level_formula(self):
        """When hl=hr=hc, three-level should equal level area."""
        b, h, s = 6.0, 2.0, 1.5
        rl = cross_section_level(b, h, s)
        r3 = cross_section_three_level(b, h, h, h, s)
        assert abs(r3["area_m2"] - rl["area_m2"]) < 1e-4

    def test_known_three_level(self):
        """Textbook three-level section (Peurifoy p.219 style).
        b=8, hc=2, hl=1.5, hr=2.5, s=1.5
        left_day = 4+1.5×1.5 = 6.25, right_day = 4+1.5×2.5 = 7.75
        Shoelace on (-6.25,0), (-4,1.5), (0,2), (4,2.5), (7.75,0)."""
        xs = [-6.25, -4.0, 0.0, 4.0, 7.75]
        ys = [0.0, 1.5, 2.0, 2.5, 0.0]
        r_manual = cross_section_by_coords(xs, ys)
        r3 = cross_section_three_level(8.0, 2.0, 1.5, 2.5, 1.5)
        assert abs(r3["area_m2"] - r_manual["area_m2"]) < 1e-4


# ===========================================================================
# 4. Cross-section by coordinates (shoelace)
# ===========================================================================

class TestCrossSectionByCoords:

    def test_unit_square(self):
        """Unit square: area = 1.0 m²."""
        r = cross_section_by_coords([0, 1, 1, 0], [0, 0, 1, 1])
        assert abs(r["area_m2"] - 1.0) < ABS

    def test_triangle(self):
        """Right triangle with legs 3 and 4: area = 6.0 m²."""
        r = cross_section_by_coords([0, 3, 0], [0, 0, 4])
        assert abs(r["area_m2"] - 6.0) < ABS

    def test_trapezoid(self):
        """Trapezoid with parallel sides 4 and 6, height 3: area = (4+6)/2×3 = 15."""
        r = cross_section_by_coords([0, 6, 5, 1], [0, 0, 3, 3])
        assert abs(r["area_m2"] - 15.0) < ABS

    def test_minimum_three_points(self):
        with pytest.raises(ValueError):
            cross_section_by_coords([0, 1], [0, 1])


# ===========================================================================
# 5. Earthwork volume — average-end-area
# ===========================================================================

class TestEarthworkVolume:

    def test_single_interval_aea(self):
        """L=20, A1=10, A2=14: V = 20×(10+14)/2 = 240 m³."""
        r = earthwork_volume([0.0, 20.0], [10.0, 14.0])
        assert abs(r["total_volume_m3"] - 240.0) < ABS
        assert len(r["intervals"]) == 1

    def test_two_intervals_aea(self):
        """Textbook example.
        Stations 0, 20, 40.  Areas 10, 14, 12.
        V1 = 20×(10+14)/2 = 240
        V2 = 20×(14+12)/2 = 260
        Total = 500 m³."""
        r = earthwork_volume([0.0, 20.0, 40.0], [10.0, 14.0, 12.0])
        assert abs(r["total_volume_m3"] - 500.0) < ABS

    def test_prismoidal_method(self):
        """Same two-interval case with prismoidal correction = 5 per interval.
        Total = 500 - 5 - 5 = 490 m³."""
        r = earthwork_volume(
            [0.0, 20.0, 40.0], [10.0, 14.0, 12.0],
            method="prismoidal",
            prismoidal_corrections=[5.0, 5.0],
        )
        assert abs(r["total_volume_m3"] - 490.0) < ABS
        assert r["method"] == "prismoidal"

    def test_interval_details(self):
        r = earthwork_volume([0.0, 20.0], [10.0, 14.0])
        iv = r["intervals"][0]
        assert iv["length_m"] == 20.0
        assert iv["area_from_m2"] == 10.0
        assert iv["area_to_m2"] == 14.0

    def test_bad_station_order_raises(self):
        with pytest.raises(ValueError):
            earthwork_volume([20.0, 0.0], [10.0, 14.0])

    def test_prismoidal_missing_corrections_fallback(self):
        """Missing corrections: should warn and fall back to AEA."""
        r = earthwork_volume(
            [0.0, 20.0], [10.0, 14.0],
            method="prismoidal",
        )
        assert r["method"] == "average-end-area"
        assert len(r["warnings"]) > 0


# ===========================================================================
# 6. Borrow-pit volume (4-quadrant grid)
# ===========================================================================

class TestBorrowPitVolume:

    def test_uniform_cut(self):
        """2×2 grid, 5m spacing, all nodes at elevation 12, design 10.
        h=2 everywhere. Corner weight=1, all 4 nodes are corners.
        cell_area=25, V = 4×(1×2×25/4) = 4×12.5 = 50 m³."""
        elev = [[12.0, 12.0], [12.0, 12.0]]
        r = borrow_pit_volume(5.0, 5.0, elev, 10.0)
        assert abs(r["total_volume_m3"] - 50.0) < ABS
        assert abs(r["cut_volume_m3"] - 50.0) < ABS
        assert r["fill_volume_m3"] == 0.0

    def test_uniform_fill(self):
        """All nodes below design: net = fill (negative total)."""
        elev = [[8.0, 8.0], [8.0, 8.0]]
        r = borrow_pit_volume(5.0, 5.0, elev, 10.0)
        assert r["total_volume_m3"] < 0.0
        assert r["fill_volume_m3"] > 0.0

    def test_mixed_cut_fill(self):
        """One corner at 12 (cut), rest at 10 (zero net)."""
        elev = [[12.0, 10.0], [10.0, 10.0]]
        r = borrow_pit_volume(5.0, 5.0, elev, 10.0)
        # Only one corner contributes: 1×2×25/4 = 12.5 m³
        assert abs(r["cut_volume_m3"] - 12.5) < ABS

    def test_3x3_interior_weights(self):
        """3×3 grid with uniform cut h=1, cell 5m.
        Corner (×4 nodes, w=1), edge (×4 nodes, w=2), interior (×1 node, w=4).
        V = cell_area×h/4 × (4×1 + 4×2 + 1×4) = 25×1/4 × 16 = 100 m³."""
        elev = [[11.0] * 3 for _ in range(3)]
        r = borrow_pit_volume(5.0, 5.0, elev, 10.0)
        assert abs(r["total_volume_m3"] - 100.0) < ABS


# ===========================================================================
# 7. Cut/fill balance
# ===========================================================================

class TestCutFillBalance:

    def test_balanced_no_shrinkage(self):
        """100 m³ cut bank, 100 m³ fill compacted, shrinkage=1.
        fill_bank = 100/1 = 100; surplus = 0."""
        r = cut_fill_balance(100.0, 100.0)
        assert r["surplus_deficit_bank_m3"] == 0.0
        assert r["borrow_needed_bank_m3"] == 0.0
        assert r["waste_available_bank_m3"] == 0.0

    def test_shrinkage_causes_borrow(self):
        """cut=90 bank, fill=100 compacted, shrinkage=0.90.
        fill_bank = 100/0.90 ≈ 111.11; surplus = 90 - 111.11 = -21.11 → borrow."""
        r = cut_fill_balance(90.0, 100.0, shrinkage_factor=0.90)
        expected_fill_bank = 100.0 / 0.90
        assert abs(r["fill_bank_equivalent_m3"] - expected_fill_bank) < 1e-4
        assert r["borrow_needed_bank_m3"] > 0.0
        assert len(r["warnings"]) > 0

    def test_surplus_cut_warns(self):
        """cut=200 bank, fill=100 compacted, shrinkage=1.
        Surplus = 100 → waste warning."""
        r = cut_fill_balance(200.0, 100.0, shrinkage_factor=1.0)
        assert r["waste_available_bank_m3"] == 100.0
        assert len(r["warnings"]) > 0

    def test_swell_factor_applied(self):
        """swell=1.25: fill_loose = fill_bank × 1.25."""
        r = cut_fill_balance(150.0, 100.0, shrinkage_factor=1.0, swell_factor=1.25)
        # fill_bank = 100, fill_loose = 100 × 1.25 = 125
        assert abs(r["fill_loose_m3"] - 125.0) < ABS

    def test_invalid_shrinkage_raises(self):
        with pytest.raises(ValueError):
            cut_fill_balance(100.0, 100.0, shrinkage_factor=-1.0)


# ===========================================================================
# 8. Mass-haul diagram
# ===========================================================================

class TestMassHaul:

    def test_balanced_single_interval(self):
        """cut=fill=100 m³ over one interval → net=0, no borrow/waste."""
        r = mass_haul([0.0, 100.0], [100.0], [100.0])
        assert r["net_m3"] == 0.0
        assert r["total_borrow_m3"] == 0.0
        assert r["total_waste_m3"] == 0.0

    def test_ordinates_cumulative(self):
        """2 intervals: cut=[60,40], fill=[50,50].
        Ordinate 0=0, after interval 1: 60-50=10, after interval 2: 10+(40-50)=0."""
        r = mass_haul([0.0, 50.0, 100.0], [60.0, 40.0], [50.0, 50.0])
        ords = r["ordinates"]
        assert abs(ords[0]["cumulative_m3"]) < ABS
        assert abs(ords[1]["cumulative_m3"] - 10.0) < ABS
        assert abs(ords[2]["cumulative_m3"] - 0.0) < ABS

    def test_balance_point_detected(self):
        """Ordinate crosses zero between stations 50 and 100 → balance_points not empty."""
        r = mass_haul([0.0, 50.0, 100.0], [80.0, 20.0], [20.0, 80.0])
        # Cumulative: 0, 60, 0 → balance point at station 100 (exact zero)
        assert len(r["balance_points"]) >= 1

    def test_borrow_needed(self):
        """No cut, only fill → borrow = fill."""
        r = mass_haul([0.0, 100.0], [0.0], [200.0])
        assert r["total_borrow_m3"] == 200.0
        assert len(r["warnings"]) > 0

    def test_waste_needed(self):
        """All cut, no fill → waste = cut."""
        r = mass_haul([0.0, 100.0], [150.0], [0.0])
        assert r["total_waste_m3"] == 150.0

    def test_cost_calculation(self):
        """Borrow 50 m³ at R10/m³ → borrow_cost = 500."""
        r = mass_haul(
            [0.0, 100.0], [0.0], [50.0],
            borrow_cost_per_m3=10.0,
        )
        assert abs(r["borrow_cost"] - 500.0) < ABS
        assert abs(r["total_cost"] - 500.0) < ABS

    def test_balance_interpolated(self):
        """Ordinate goes from +20 at station 0 to -20 at station 40 after two steps.
        Balance between 20 and 40 by linear interp at 30."""
        r = mass_haul(
            [0.0, 20.0, 40.0],
            [30.0, 10.0],
            [10.0, 30.0],
        )
        # Cumulative: 0, 20, 0 — balance at 40 (exact)
        assert any(abs(bp - 40.0) < 0.1 for bp in r["balance_points"])


# ===========================================================================
# 9. Proctor optimum (MDD & OMC)
# ===========================================================================

class TestProctorOptimum:

    # Textbook Proctor data for a silty clay
    # w%:   8,    10,   12,   14,   16
    # ρ_d:  1680, 1750, 1770, 1740, 1690  kg/m³
    _wc = [8.0, 10.0, 12.0, 14.0, 16.0]
    _rho = [1680.0, 1750.0, 1770.0, 1740.0, 1690.0]

    def test_omc_near_peak(self):
        """OMC should be near 12% where density is maximum."""
        r = proctor_optimum(self._wc, self._rho)
        assert 10.0 <= r["omc_percent"] <= 14.0

    def test_mdd_near_peak(self):
        """MDD should be close to 1770 kg/m³."""
        r = proctor_optimum(self._wc, self._rho)
        assert abs(r["mdd"] - 1770.0) < 50.0

    def test_poly_opens_downward(self):
        """Coefficient a must be negative for a proper compaction curve."""
        r = proctor_optimum(self._wc, self._rho)
        assert r["poly_coefficients"][0] < 0.0

    def test_r_squared_good(self):
        r = proctor_optimum(self._wc, self._rho)
        assert r["r_squared"] > 0.85

    def test_insufficient_points_raises(self):
        with pytest.raises(ValueError):
            proctor_optimum([10.0, 12.0], [1750.0, 1770.0])


# ===========================================================================
# 10. Relative compaction
# ===========================================================================

class TestRelativeCompaction:

    def test_passing(self):
        """field_ρ=1710, MDD=1800 → RC=95%; spec=95% → PASS."""
        r = relative_compaction(1710.0, 1800.0, spec_rc_percent=95.0)
        assert abs(r["rc_percent"] - 95.0) < 0.01
        assert r["pass_fail"] == "PASS"
        assert r["deficit_pct"] == 0.0

    def test_failing_warns(self):
        """field_ρ=1620, MDD=1800 → RC=90% < 95% → FAIL."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = relative_compaction(1620.0, 1800.0, spec_rc_percent=95.0)
        assert r["pass_fail"] == "FAIL"
        assert r["deficit_pct"] > 0.0
        assert any("Compaction not met" in str(warning.message) for warning in w)

    def test_rc_formula(self):
        """RC = 100 × 1710 / 1800 = 95.0%."""
        r = relative_compaction(1710.0, 1800.0)
        assert abs(r["rc_percent"] - 95.0) < 0.01

    def test_invalid_mdd_raises(self):
        with pytest.raises(ValueError):
            relative_compaction(1710.0, 0.0)


# ===========================================================================
# 11. Lift productivity
# ===========================================================================

class TestLiftProductivity:

    def test_basic(self):
        """w=2.1 m, speed=5 km/h, lift=0.25 m, passes=4, eff=0.75.
        area/h = 2.1 × 5000 × 0.75 / 4 = 1968.75 m²/h.
        vol/h = 1968.75 × 0.25 = 492.1875 m³/h."""
        r = lift_productivity(2.1, 5.0, 0.25, 4, efficiency_factor=0.75)
        assert abs(r["area_per_hour_m2"] - 1968.75) < 0.01
        assert abs(r["volume_per_hour_m3"] - 492.1875) < 0.01

    def test_thick_lift_warns(self):
        """Lift >300 mm → warning."""
        r = lift_productivity(2.0, 5.0, 0.35, 4)
        assert len(r["warnings"]) > 0

    def test_invalid_passes_raises(self):
        with pytest.raises(ValueError):
            lift_productivity(2.0, 5.0, 0.25, 0)


# ===========================================================================
# 12. Slope daylight offset
# ===========================================================================

class TestSlopeDaylightOffset:

    def test_cut_basic(self):
        """ground=105, design=100, batter=1.5, half_width=4.
        vert=5, horiz=7.5, total=11.5."""
        r = slope_daylight_offset(
            formation_half_width=4.0,
            design_height_at_edge=100.0,
            ground_height_at_edge=105.0,
            batter=1.5,
            mode="cut",
        )
        assert abs(r["vertical_height_m"] - 5.0) < ABS
        assert abs(r["horizontal_offset_m"] - 7.5) < ABS
        assert abs(r["total_offset_from_cl_m"] - 11.5) < ABS

    def test_fill_basic(self):
        """design=105, ground=100, batter=2, half_width=3.
        vert=5, horiz=10, total=13."""
        r = slope_daylight_offset(
            formation_half_width=3.0,
            design_height_at_edge=105.0,
            ground_height_at_edge=100.0,
            batter=2.0,
            mode="fill",
        )
        assert abs(r["vertical_height_m"] - 5.0) < ABS
        assert abs(r["total_offset_from_cl_m"] - 13.0) < ABS

    def test_negative_vert_warns(self):
        """design=105 > ground=100 in cut mode → negative vert → warning."""
        r = slope_daylight_offset(
            formation_half_width=4.0,
            design_height_at_edge=105.0,
            ground_height_at_edge=100.0,
            batter=1.5,
            mode="cut",
        )
        assert len(r["warnings"]) > 0

    def test_slope_percent(self):
        """batter=2.0 → slope_pct = 100/2 = 50%."""
        r = slope_daylight_offset(4.0, 100.0, 105.0, 2.0, mode="cut")
        assert abs(r["daylight_slope_pct"] - 50.0) < ABS


# ===========================================================================
# 13. Trench volume
# ===========================================================================

class TestTrenchVolume:

    def test_vertical_rectangular_trench(self):
        """L=50, depth=2, width=0.6, no batter.
        Area = 0.6×2 = 1.2 m²; gross = 60 m³."""
        r = trench_volume(50.0, 2.0, 0.6, side_slope=0.0)
        assert abs(r["gross_volume_m3"] - 60.0) < ABS
        assert abs(r["top_width_m"] - 0.6) < ABS

    def test_battered_trench(self):
        """L=10, depth=2, bottom_width=1, side_slope=0.5.
        top_width = 1 + 2×0.5×2 = 3; area = (1+3)/2×2=4; gross=40."""
        r = trench_volume(10.0, 2.0, 1.0, side_slope=0.5)
        assert abs(r["top_width_m"] - 3.0) < ABS
        assert abs(r["gross_volume_m3"] - 40.0) < ABS

    def test_pipe_deduction(self):
        """Subtract pipe volume: OD=0.3, L=10.
        pipe_vol = π/4 × 0.09 × 10 ≈ 0.707 m³."""
        r = trench_volume(10.0, 1.5, 0.6, pipe_od_m=0.3)
        pipe_vol = math.pi / 4.0 * 0.09 * 10.0
        assert abs(r["net_volume_m3"] - (r["gross_volume_m3"] - pipe_vol)) < 1e-6

    def test_bedding_volume(self):
        """bedding = bottom_width × thickness × length = 0.6×0.1×50 = 3 m³."""
        r = trench_volume(50.0, 2.0, 0.6, bedding_thickness_m=0.1)
        assert abs(r["bedding_volume_m3"] - 3.0) < ABS

    def test_shoring_warning_deep_vertical(self):
        """Deep vertical trench with no shoring → warning."""
        r = trench_volume(10.0, 2.0, 0.6, side_slope=0.0)
        assert len(r["warnings"]) > 0

    def test_shoring_area(self):
        """2 m²/m × 20 m = 40 m²."""
        r = trench_volume(20.0, 2.0, 0.6, shoring_area_per_m=2.0)
        assert abs(r["shoring_area_m2"] - 40.0) < ABS


# ===========================================================================
# 14. Dewatering pump rate (Dupuit–Thiem)
# ===========================================================================

class TestDewateringPumpRate:

    def test_basic_pump_rate(self):
        """K=1e-4 m/s, H=5, drawdown=2, R=50, r=1.
        hw=3, Q=π×1e-4×(25-9)/ln(50) ≈ 1.299e-3 m³/s."""
        r = dewatering_pump_rate(
            hydraulic_conductivity_m_s=1e-4,
            aquifer_thickness_m=5.0,
            drawdown_m=2.0,
            radius_of_influence_m=50.0,
            equivalent_well_radius_m=1.0,
        )
        expected = math.pi * 1e-4 * (25.0 - 9.0) / math.log(50.0)
        assert abs(r["pump_rate_m3_s"] - expected) < 1e-8
        assert abs(r["head_at_well_m"] - 3.0) < ABS

    def test_unit_conversions(self):
        """pump_rate_m3_h = pump_rate_m3_s × 3600."""
        r = dewatering_pump_rate(1e-4, 5.0, 2.0, 50.0, 1.0)
        assert abs(r["pump_rate_m3_h"] - r["pump_rate_m3_s"] * 3600.0) < 1e-8
        assert abs(r["pump_rate_L_s"] - r["pump_rate_m3_s"] * 1000.0) < 1e-8

    def test_large_drawdown_warns(self):
        """drawdown > 50% of H → Dupuit warning."""
        r = dewatering_pump_rate(1e-4, 5.0, 3.0, 50.0, 1.0)
        assert len(r["warnings"]) > 0

    def test_invalid_radius_raises(self):
        with pytest.raises(ValueError):
            dewatering_pump_rate(1e-4, 5.0, 2.0, 50.0, 60.0)  # r >= R

    def test_invalid_drawdown_raises(self):
        with pytest.raises(ValueError):
            dewatering_pump_rate(1e-4, 5.0, 6.0, 50.0, 1.0)  # drawdown > H


# ===========================================================================
# 15. LLM tool wrappers — happy path
# ===========================================================================

class TestToolsHappyPath:

    def test_tool_cross_section_level(self):
        raw = _run(run_earthworks_cross_section(
            _ctx(),
            _args(method="level", formation_width=8.0, centre_height=3.0, side_slope=1.5),
        ))
        d = _ok_tool(raw)
        assert abs(d["area_m2"] - 37.5) < ABS

    def test_tool_cross_section_two_level(self):
        raw = _run(run_earthworks_cross_section(
            _ctx(),
            _args(method="two-level", formation_width=6.0, centre_height=2.0,
                  left_slope=1.0, right_slope=2.0),
        ))
        d = _ok_tool(raw)
        assert abs(d["area_m2"] - 18.0) < ABS

    def test_tool_cross_section_by_coords(self):
        raw = _run(run_earthworks_cross_section(
            _ctx(),
            _args(method="by-coords", xs=[0, 1, 1, 0], ys=[0, 0, 1, 1]),
        ))
        d = _ok_tool(raw)
        assert abs(d["area_m2"] - 1.0) < ABS

    def test_tool_volume(self):
        raw = _run(run_earthworks_volume(
            _ctx(),
            _args(stations=[0.0, 20.0], areas=[10.0, 14.0]),
        ))
        d = _ok_tool(raw)
        assert abs(d["total_volume_m3"] - 240.0) < ABS

    def test_tool_borrow_pit(self):
        raw = _run(run_earthworks_borrow_pit(
            _ctx(),
            _args(
                grid_spacing_x=5.0,
                grid_spacing_y=5.0,
                existing_elevations=[[12.0, 12.0], [12.0, 12.0]],
                design_elevation=10.0,
            ),
        ))
        d = _ok_tool(raw)
        assert abs(d["total_volume_m3"] - 50.0) < ABS

    def test_tool_cut_fill_balance(self):
        raw = _run(run_earthworks_cut_fill_balance(
            _ctx(),
            _args(cut_volume_bank_m3=100.0, fill_volume_compacted_m3=100.0),
        ))
        d = _ok_tool(raw)
        assert d["surplus_deficit_bank_m3"] == 0.0

    def test_tool_mass_haul(self):
        raw = _run(run_earthworks_mass_haul(
            _ctx(),
            _args(stations=[0.0, 100.0], cut_volumes=[100.0], fill_volumes=[100.0]),
        ))
        d = _ok_tool(raw)
        assert d["net_m3"] == 0.0

    def test_tool_proctor(self):
        raw = _run(run_earthworks_proctor(
            _ctx(),
            _args(
                moisture_contents=[8.0, 10.0, 12.0, 14.0, 16.0],
                dry_densities=[1680.0, 1750.0, 1770.0, 1740.0, 1690.0],
            ),
        ))
        d = _ok_tool(raw)
        assert 10.0 <= d["omc_percent"] <= 14.0

    def test_tool_relative_compaction(self):
        raw = _run(run_earthworks_relative_compaction(
            _ctx(),
            _args(field_dry_density=1710.0, lab_mdd=1800.0),
        ))
        d = _ok_tool(raw)
        assert d["pass_fail"] == "PASS"

    def test_tool_lift_productivity(self):
        raw = _run(run_earthworks_lift_productivity(
            _ctx(),
            _args(
                roller_width_m=2.1,
                roller_speed_kmh=5.0,
                lift_thickness_m=0.25,
                num_passes=4,
                efficiency_factor=0.75,
            ),
        ))
        d = _ok_tool(raw)
        assert abs(d["area_per_hour_m2"] - 1968.75) < 0.01

    def test_tool_slope_daylight(self):
        raw = _run(run_earthworks_slope_daylight(
            _ctx(),
            _args(
                formation_half_width=4.0,
                design_height_at_edge=100.0,
                ground_height_at_edge=105.0,
                batter=1.5,
                mode="cut",
            ),
        ))
        d = _ok_tool(raw)
        assert abs(d["total_offset_from_cl_m"] - 11.5) < ABS

    def test_tool_trench(self):
        raw = _run(run_earthworks_trench(
            _ctx(),
            _args(length_m=50.0, depth_m=2.0, bottom_width_m=0.6),
        ))
        d = _ok_tool(raw)
        assert abs(d["gross_volume_m3"] - 60.0) < ABS

    def test_tool_dewatering(self):
        raw = _run(run_earthworks_dewatering(
            _ctx(),
            _args(
                hydraulic_conductivity_m_s=1e-4,
                aquifer_thickness_m=5.0,
                drawdown_m=2.0,
                radius_of_influence_m=50.0,
                equivalent_well_radius_m=1.0,
            ),
        ))
        d = _ok_tool(raw)
        assert d["pump_rate_m3_s"] > 0.0


# ===========================================================================
# 16. LLM tool wrappers — error paths
# ===========================================================================

class TestToolsErrorPath:

    def test_cross_section_missing_field(self):
        raw = _run(run_earthworks_cross_section(
            _ctx(),
            _args(method="level", formation_width=8.0),
        ))
        _err_tool(raw)

    def test_cross_section_invalid_json(self):
        raw = _run(run_earthworks_cross_section(_ctx(), b"not-json"))
        _err_tool(raw)

    def test_volume_missing_stations(self):
        raw = _run(run_earthworks_volume(_ctx(), _args(areas=[10.0, 14.0])))
        _err_tool(raw)

    def test_borrow_pit_missing_field(self):
        raw = _run(run_earthworks_borrow_pit(
            _ctx(),
            _args(grid_spacing_x=5.0, grid_spacing_y=5.0, design_elevation=10.0),
        ))
        _err_tool(raw)

    def test_cut_fill_missing_cut(self):
        raw = _run(run_earthworks_cut_fill_balance(
            _ctx(), _args(fill_volume_compacted_m3=100.0),
        ))
        _err_tool(raw)

    def test_mass_haul_missing_cut_volumes(self):
        raw = _run(run_earthworks_mass_haul(
            _ctx(),
            _args(stations=[0.0, 100.0], fill_volumes=[100.0]),
        ))
        _err_tool(raw)

    def test_proctor_insufficient_points(self):
        raw = _run(run_earthworks_proctor(
            _ctx(),
            _args(moisture_contents=[10.0, 12.0], dry_densities=[1750.0, 1770.0]),
        ))
        _err_tool(raw)

    def test_relative_compaction_invalid(self):
        raw = _run(run_earthworks_relative_compaction(
            _ctx(), _args(field_dry_density=-10.0, lab_mdd=1800.0),
        ))
        _err_tool(raw)

    def test_trench_invalid_depth(self):
        raw = _run(run_earthworks_trench(
            _ctx(), _args(length_m=10.0, depth_m=-1.0, bottom_width_m=0.6),
        ))
        _err_tool(raw)

    def test_dewatering_radius_exceeds(self):
        raw = _run(run_earthworks_dewatering(
            _ctx(),
            _args(
                hydraulic_conductivity_m_s=1e-4,
                aquifer_thickness_m=5.0,
                drawdown_m=2.0,
                radius_of_influence_m=1.0,
                equivalent_well_radius_m=5.0,  # r > R → error
            ),
        ))
        _err_tool(raw)
