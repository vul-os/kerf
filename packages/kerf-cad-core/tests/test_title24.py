"""
Tests for kerf_cad_core.buildingenergy.title24_compliance

Tests cover:
  - Title 24 baseline tables return non-zero values for all 16 CA climate zones
  - All building types return baseline TDV for each CZ
  - Compliant building: proposed TDV < baseline → compliant=True
  - Non-compliant building: proposed TDV > baseline → compliant=False
  - Margin % calculation is accurate
  - Invalid CZ raises ValueError
  - Invalid building type raises ValueError
  - Gas vs electric heating changes TDV breakdown
  - TDV breakdown keys present
  - High peak cooling load triggers mandatory check warning
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.buildingenergy.hourly_8760 import AnnualResult, HourlyResult
from kerf_cad_core.buildingenergy.title24_compliance import (
    Title24Spec,
    Title24Report,
    check_title24_compliance,
    _T24_BASELINE_TDV,
    _compute_tdv_from_annual,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _minimal_annual(
    heating_kwh: float = 5000.0,
    cooling_kwh: float = 10000.0,
    fan_kwh: float = 2000.0,
    lighting_kwh: float = 3000.0,
    peak_cooling_kw: float = 10.0,
    floor_area_m2: float = 500.0,
) -> AnnualResult:
    """Build minimal AnnualResult without hourly list."""
    eui = (heating_kwh + cooling_kwh + fan_kwh + lighting_kwh) / floor_area_m2
    return AnnualResult(
        hourly=[],
        annual_heating_kwh=heating_kwh,
        annual_cooling_kwh=cooling_kwh,
        annual_fan_kwh=fan_kwh,
        annual_lighting_kwh=lighting_kwh,
        eui_kwh_m2_yr=eui,
        peak_cooling_kw=peak_cooling_kw,
        peak_heating_kw=0.0,
    )


# ---------------------------------------------------------------------------
# Baseline table tests
# ---------------------------------------------------------------------------

class TestTitle24BaselineTable:

    def test_all_16_zones_office(self):
        """All 16 California climate zones must have a baseline TDV for office."""
        for cz in range(1, 17):
            assert cz in _T24_BASELINE_TDV["office"], f"Missing CZ{cz} in office baseline"
            assert _T24_BASELINE_TDV["office"][cz] > 0

    def test_all_16_zones_retail(self):
        for cz in range(1, 17):
            assert cz in _T24_BASELINE_TDV["retail"]
            assert _T24_BASELINE_TDV["retail"][cz] > 0

    def test_all_16_zones_school(self):
        for cz in range(1, 17):
            assert cz in _T24_BASELINE_TDV["school"]
            assert _T24_BASELINE_TDV["school"][cz] > 0

    def test_all_16_zones_hospital(self):
        for cz in range(1, 17):
            assert cz in _T24_BASELINE_TDV["hospital"]
            assert _T24_BASELINE_TDV["hospital"][cz] > 0

    def test_all_16_zones_residential(self):
        for cz in range(1, 17):
            assert cz in _T24_BASELINE_TDV["residential"]
            assert _T24_BASELINE_TDV["residential"][cz] > 0

    def test_hot_zone15_higher_than_coastal_zone7(self):
        """Palm Springs (CZ15) should have higher cooling TDV than San Diego (CZ7)."""
        assert _T24_BASELINE_TDV["office"][15] > _T24_BASELINE_TDV["office"][7]

    def test_residential_lower_than_office(self):
        """Residential TDV baselines should be lower than office (lower LPD)."""
        for cz in range(1, 17):
            assert _T24_BASELINE_TDV["residential"][cz] < _T24_BASELINE_TDV["office"][cz], (
                f"CZ{cz}: residential {_T24_BASELINE_TDV['residential'][cz]} should be < "
                f"office {_T24_BASELINE_TDV['office'][cz]}"
            )


# ---------------------------------------------------------------------------
# Compliance check tests
# ---------------------------------------------------------------------------

class TestCheckTitle24Compliance:

    def test_compliant_office_cz4(self):
        """Small efficient office in CZ4 should be compliant."""
        annual = _minimal_annual(heating_kwh=2000, cooling_kwh=3000, fan_kwh=500,
                                  lighting_kwh=1000, floor_area_m2=500)
        spec = Title24Spec(climate_zone=4, building_type="office", floor_area_m2=500,
                           occupancy_type="office")
        report = check_title24_compliance(spec, annual)
        assert isinstance(report, Title24Report)
        assert report.compliant is True
        assert report.margin_pct > 0

    def test_noncompliant_office_very_high_energy(self):
        """Building with very high energy use should fail compliance."""
        annual = _minimal_annual(heating_kwh=100000, cooling_kwh=200000, fan_kwh=50000,
                                  lighting_kwh=80000, floor_area_m2=200)
        spec = Title24Spec(climate_zone=9, building_type="office", floor_area_m2=200,
                           occupancy_type="office")
        report = check_title24_compliance(spec, annual)
        assert report.compliant is False
        assert report.margin_pct < 0
        assert len(report.failures) >= 1

    def test_margin_pct_formula(self):
        """Verify margin_pct = (baseline - proposed) / baseline × 100."""
        annual = _minimal_annual(floor_area_m2=1000)
        spec = Title24Spec(climate_zone=3, building_type="office", floor_area_m2=1000,
                           occupancy_type="office")
        report = check_title24_compliance(spec, annual)
        expected_margin = (report.baseline_tdv - report.proposed_tdv) / report.baseline_tdv * 100.0
        assert abs(report.margin_pct - expected_margin) < 0.01

    def test_tdv_breakdown_keys_present(self):
        annual = _minimal_annual(floor_area_m2=500)
        spec = Title24Spec(climate_zone=6, building_type="retail", floor_area_m2=500,
                           occupancy_type="retail")
        report = check_title24_compliance(spec, annual)
        assert "heating" in report.tdv_breakdown
        assert "cooling" in report.tdv_breakdown
        assert "lighting" in report.tdv_breakdown
        assert "fans" in report.tdv_breakdown

    def test_electric_heating_higher_tdv_than_gas(self):
        """Electric resistance heating has higher TDV than gas heating."""
        annual = _minimal_annual(heating_kwh=10000, cooling_kwh=5000, floor_area_m2=500)
        spec_gas = Title24Spec(climate_zone=5, building_type="office", floor_area_m2=500,
                               occupancy_type="office", heating_fuel="gas")
        spec_elec = Title24Spec(climate_zone=5, building_type="office", floor_area_m2=500,
                                occupancy_type="office", heating_fuel="electric")
        report_gas = check_title24_compliance(spec_gas, annual)
        report_elec = check_title24_compliance(spec_elec, annual)
        assert report_elec.proposed_tdv > report_gas.proposed_tdv, (
            "Electric heating TDV should be higher than gas"
        )

    def test_hospital_higher_baseline_than_office(self):
        annual = _minimal_annual(floor_area_m2=1000)
        spec_hosp = Title24Spec(climate_zone=12, building_type="hospital", floor_area_m2=1000,
                                occupancy_type="hospital")
        spec_off = Title24Spec(climate_zone=12, building_type="office", floor_area_m2=1000,
                               occupancy_type="office")
        r_hosp = check_title24_compliance(spec_hosp, annual)
        r_off = check_title24_compliance(spec_off, annual)
        assert r_hosp.baseline_tdv > r_off.baseline_tdv

    def test_education_synonym_accepted(self):
        """'education' should map to 'school' baseline."""
        annual = _minimal_annual(floor_area_m2=500)
        spec = Title24Spec(climate_zone=4, building_type="education", floor_area_m2=500,
                           occupancy_type="school")
        report = check_title24_compliance(spec, annual)
        assert report.baseline_tdv > 0

    def test_invalid_cz_raises(self):
        annual = _minimal_annual()
        spec = Title24Spec(climate_zone=0, building_type="office", floor_area_m2=500,
                           occupancy_type="office")
        with pytest.raises(ValueError, match="climate_zone"):
            check_title24_compliance(spec, annual)

    def test_invalid_cz_17_raises(self):
        annual = _minimal_annual()
        spec = Title24Spec(climate_zone=17, building_type="office", floor_area_m2=500,
                           occupancy_type="office")
        with pytest.raises(ValueError, match="climate_zone"):
            check_title24_compliance(spec, annual)

    def test_invalid_building_type_raises(self):
        annual = _minimal_annual()
        spec = Title24Spec(climate_zone=5, building_type="datacenter", floor_area_m2=500,
                           occupancy_type="datacenter")
        with pytest.raises(ValueError):
            check_title24_compliance(spec, annual)

    def test_all_16_zones_return_result(self):
        """All 16 CA climate zones complete without error."""
        for cz in range(1, 17):
            annual = _minimal_annual(floor_area_m2=500)
            spec = Title24Spec(climate_zone=cz, building_type="office", floor_area_m2=500,
                               occupancy_type="office")
            report = check_title24_compliance(spec, annual)
            assert report.baseline_tdv > 0, f"CZ{cz} returned zero baseline"

    def test_caveat_present(self):
        annual = _minimal_annual()
        spec = Title24Spec(climate_zone=8, building_type="office", floor_area_m2=500,
                           occupancy_type="office")
        report = check_title24_compliance(spec, annual)
        assert len(report.honest_caveat) > 20

    def test_high_peak_cooling_triggers_warning(self):
        """Peak cooling density > 250 W/m² should trigger air leakage warning."""
        # peak_cooling_kw=300, floor_area_m2=200 → 300/200 = 1.5 kW/m² = 1500 W/m²
        annual = _minimal_annual(
            cooling_kwh=50000, floor_area_m2=200, peak_cooling_kw=300.0
        )
        spec = Title24Spec(climate_zone=15, building_type="office", floor_area_m2=200,
                           occupancy_type="office")
        report = check_title24_compliance(spec, annual)
        # Failures should include air-leakage warning
        has_air_leakage = any("air" in f.lower() or "§110.2" in f for f in report.failures)
        assert has_air_leakage, f"Expected air leakage warning; got failures: {report.failures}"
