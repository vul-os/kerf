"""
Tests for T-112: full stair / ramp model.

DoD: a multi-flight U-stair + a ramp with two landings IFC-export
correctly; pytest.
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.stairs import (
    StairFlight,
    StairLanding,
    WinderGroup,
    Stair,
    StairValidationError,
    Ramp,
    RampFlight,
    RampLanding,
    check_stair_code,
    make_stair,
    make_u_stair,
    make_ramp,
    stair_to_ifc_dict,
    ramp_to_ifc_dict,
    HANDRAIL_DEFAULTS,
    CODE_LIMITS,
)


# =============================================================================
# Code-compliance checks
# =============================================================================

class TestCodeCompliance:
    def test_compliant_stair(self):
        """IBC 2021 compliant: riser=175, tread=279, width=1200."""
        violations = check_stair_code(riser_mm=175.0, tread_mm=279.0, width_mm=1200.0)
        assert violations == []

    def test_riser_too_high(self):
        violations = check_stair_code(riser_mm=190.0, tread_mm=280.0, width_mm=1200.0)
        assert any("Riser" in v for v in violations)

    def test_riser_too_low(self):
        violations = check_stair_code(riser_mm=90.0, tread_mm=300.0, width_mm=1200.0)
        assert any("Riser" in v for v in violations)

    def test_tread_too_short(self):
        violations = check_stair_code(riser_mm=175.0, tread_mm=200.0, width_mm=1200.0)
        assert any("Tread" in v for v in violations)

    def test_2r_plus_t_too_low(self):
        # 2*100 + 200 = 400 < 550
        violations = check_stair_code(riser_mm=100.0, tread_mm=200.0, width_mm=1200.0)
        assert any("2R+T" in v for v in violations)

    def test_width_too_narrow(self):
        violations = check_stair_code(riser_mm=175.0, tread_mm=280.0, width_mm=800.0)
        assert any("width" in v.lower() for v in violations)

    def test_boundary_values_compliant(self):
        # IBC max riser = 178 mm, min tread = 279 mm → 2R+T = 356+279 = 635 ✓
        violations = check_stair_code(riser_mm=178.0, tread_mm=279.0, width_mm=914.4)
        assert violations == []


# =============================================================================
# StairFlight
# =============================================================================

class TestStairFlight:
    def _make_flight(self, steps=10, riser=175.0, tread=280.0) -> StairFlight:
        return StairFlight(
            id="f1",
            start=[0.0, 0.0, 0.0],
            direction=[1.0, 0.0],
            step_count=steps,
            riser_mm=riser,
            tread_mm=tread,
            width_mm=1200.0,
        )

    def test_total_rise(self):
        f = self._make_flight(steps=10, riser=175.0)
        assert abs(f.total_rise - 1750.0) < 1e-6

    def test_total_run(self):
        f = self._make_flight(steps=10, tread=280.0)
        assert abs(f.total_run - 2800.0) < 1e-6

    def test_end_point_position(self):
        f = self._make_flight(steps=10, riser=175.0, tread=280.0)
        ep = f.end_point
        assert abs(ep[0] - 2800.0) < 1e-6   # X: 10*280
        assert abs(ep[2] - 1750.0) < 1e-6   # Z: 10*175

    def test_direction_normalised(self):
        f = StairFlight(
            id="f1", start=[0, 0, 0], direction=[3.0, 4.0],
            step_count=5, riser_mm=175.0, tread_mm=280.0,
        )
        dx, dy = f.direction
        assert abs(math.sqrt(dx*dx + dy*dy) - 1.0) < 1e-9

    def test_zero_direction_raises(self):
        with pytest.raises(StairValidationError):
            StairFlight(id="f", start=[0,0,0], direction=[0,0],
                        step_count=5, riser_mm=175, tread_mm=280)

    def test_zero_steps_raises(self):
        with pytest.raises(StairValidationError):
            StairFlight(id="f", start=[0,0,0], direction=[1,0],
                        step_count=0, riser_mm=175, tread_mm=280)


# =============================================================================
# T-112 DoD: U-stair (multi-flight)
# =============================================================================

class TestUStair:
    def _u_stair(self, total_rise=3000.0, riser=150.0, tread=279.0) -> Stair:
        return make_u_stair(
            name="Test U-Stair",
            total_rise_mm=total_rise,
            riser_mm=riser,
            tread_mm=tread,
            width_mm=1200.0,
        )

    def test_two_flights(self):
        stair = self._u_stair()
        assert len(stair.flights) == 2

    def test_one_landing(self):
        stair = self._u_stair()
        assert len(stair.landings) == 1

    def test_total_rise_correct(self):
        stair = self._u_stair(total_rise=3000.0)
        assert abs(stair.total_rise - 3000.0) < 5.0   # rounding on steps

    def test_flight_ids_unique(self):
        stair = self._u_stair()
        ids = [f.id for f in stair.flights]
        assert len(ids) == len(set(ids))

    def test_landing_height_between_flights(self):
        """Landing z must be between start z and end z of the full stair."""
        stair = self._u_stair(total_rise=3000.0)
        landing_z = stair.landings[0].position[2]
        # Landing should be at approximately half the total rise
        assert landing_z > 0
        assert landing_z < stair.total_rise

    def test_ifc_export_keys(self):
        stair = self._u_stair()
        d = stair_to_ifc_dict(stair)
        for key in ("kind", "name", "construction", "material",
                    "total_rise_mm", "total_run_mm", "flights",
                    "landings", "code_violations"):
            assert key in d

    def test_ifc_export_kind_stair(self):
        stair = self._u_stair()
        d = stair_to_ifc_dict(stair)
        assert d["kind"] == "stair"

    def test_ifc_export_flights_count(self):
        stair = self._u_stair()
        d = stair_to_ifc_dict(stair)
        assert len(d["flights"]) == 2

    def test_ifc_export_landings_count(self):
        stair = self._u_stair()
        d = stair_to_ifc_dict(stair)
        assert len(d["landings"]) == 1

    def test_ifc_export_flight_keys(self):
        stair = self._u_stair()
        d = stair_to_ifc_dict(stair)
        for flight_dict in d["flights"]:
            for key in ("id", "start", "direction", "step_count",
                        "riser_mm", "tread_mm", "total_rise_mm",
                        "total_run_mm", "end_point"):
                assert key in flight_dict

    def test_code_violations_empty_for_compliant(self):
        """IBC-compliant U-stair should have no violations."""
        stair = make_u_stair(
            total_rise_mm=3000.0, riser_mm=150.0, tread_mm=280.0, width_mm=1200.0
        )
        d = stair_to_ifc_dict(stair)
        assert d["code_violations"] == []

    def test_monolithic_construction_default(self):
        stair = self._u_stair()
        assert stair.construction == "monolithic"

    def test_assembled_construction(self):
        stair = make_u_stair(construction="assembled")
        assert stair.construction == "assembled"


# =============================================================================
# T-112 DoD: Ramp with two landings
# =============================================================================

class TestRampWithLandings:
    def _ramp(self, num_flights=3) -> Ramp:
        return make_ramp(
            name="Test Ramp",
            total_rise_mm=600.0,
            slope_percent=8.33,
            width_mm=1500.0,
            num_flights=num_flights,
        )

    def test_three_flights_two_landings(self):
        """DoD: ramp with two landings = 3 flights."""
        ramp = self._ramp(num_flights=3)
        assert len(ramp.flights) == 3
        assert len(ramp.landings) == 2

    def test_two_flights_one_landing(self):
        ramp = self._ramp(num_flights=2)
        assert len(ramp.flights) == 2
        assert len(ramp.landings) == 1

    def test_total_rise_correct(self):
        ramp = self._ramp(num_flights=3)
        assert abs(ramp.total_rise - 600.0) < 1.0

    def test_total_run_positive(self):
        ramp = self._ramp(num_flights=3)
        assert ramp.total_run > 0

    def test_ramp_flight_rise(self):
        """Each flight rise = total_rise / num_flights."""
        ramp = self._ramp(num_flights=3)
        expected_rise = 600.0 / 3
        for flt in ramp.flights:
            assert abs(flt.rise_mm - expected_rise) < 0.5

    def test_end_point_z_increases(self):
        ramp = self._ramp(num_flights=3)
        for flt in ramp.flights:
            assert flt.end_point[2] > flt.start[2]

    def test_ifc_export_keys(self):
        ramp = self._ramp(num_flights=3)
        d = ramp_to_ifc_dict(ramp)
        for key in ("kind", "name", "material", "total_rise_mm",
                    "total_run_mm", "flights", "landings", "has_handrail"):
            assert key in d

    def test_ifc_export_kind_ramp(self):
        ramp = self._ramp()
        assert ramp_to_ifc_dict(ramp)["kind"] == "ramp"

    def test_ifc_export_flight_keys(self):
        ramp = self._ramp()
        d = ramp_to_ifc_dict(ramp)
        for flt_d in d["flights"]:
            for key in ("id", "start", "direction", "length_mm",
                        "width_mm", "slope_percent", "rise_mm", "end_point"):
                assert key in flt_d

    def test_ifc_export_landing_keys(self):
        ramp = self._ramp(num_flights=3)
        d = ramp_to_ifc_dict(ramp)
        for lan_d in d["landings"]:
            assert "id" in lan_d
            assert "position" in lan_d
            assert "size_mm" in lan_d

    def test_invalid_num_flights_raises(self):
        with pytest.raises(StairValidationError):
            make_ramp(num_flights=0)

    def test_slope_too_steep_raises(self):
        with pytest.raises(StairValidationError):
            RampFlight(id="r", start=[0,0,0], direction=[1,0],
                       length_mm=5000.0, slope_percent=40.0)

    def test_ada_compliant_slope(self):
        """ADA max slope 8.33 % (1:12) should create valid ramp."""
        ramp = make_ramp(slope_percent=8.33, total_rise_mm=600.0)
        assert ramp.total_rise > 0


# =============================================================================
# Winder groups
# =============================================================================

class TestWinderGroup:
    def test_basic_winder(self):
        w = WinderGroup(
            id="w1",
            centre=[0.0, 0.0, 1750.0],
            angle_deg=90.0,
            winder_count=3,
            riser_mm=175.0,
        )
        assert w.angle_deg == 90.0
        assert w.winder_count == 3

    def test_too_few_winders_raises(self):
        with pytest.raises(StairValidationError):
            WinderGroup(id="w", centre=[0, 0, 0], angle_deg=90, winder_count=1, riser_mm=175)

    def test_invalid_angle_raises(self):
        with pytest.raises(StairValidationError):
            WinderGroup(id="w", centre=[0,0,0], angle_deg=0, winder_count=3, riser_mm=175)

    def test_full_stair_with_winders(self):
        """Stair with winders exported correctly."""
        f1 = StairFlight(id="f1", start=[0,0,0], direction=[1,0],
                         step_count=8, riser_mm=175, tread_mm=280)
        w = WinderGroup(id="w1", centre=[f1.end_point[0], 0, f1.end_point[2]],
                        angle_deg=90, winder_count=3, riser_mm=175)
        f2 = StairFlight(id="f2", start=[f1.end_point[0], 1200, f1.end_point[2]],
                         direction=[0, 1, 0][:2],  # type: ignore
                         step_count=8, riser_mm=175, tread_mm=280)
        stair = make_stair("L-Stair", flights=[f1, f2], winders=[w])
        d = stair_to_ifc_dict(stair)
        assert len(d["winders"]) == 1
        assert d["winders"][0]["angle_deg"] == 90.0
