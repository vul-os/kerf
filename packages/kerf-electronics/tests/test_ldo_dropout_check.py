"""
Tests for LDO dropout and thermal compliance checker.

Reference design used throughout:
  5V input → 3.3V LDO, V_in 4.8–5.2V, I_load=500mA, dropout=200mV, R_θja=80K/W
  headroom = (4.8 - 3.3) × 1000 = 1500 mV  (OK vs 200 mV dropout spec)
  P_diss   = (5.2 - 3.3) × 0.5  = 0.95 W
  T_j      = 25 + 0.95 × 80     = 25 + 76 = 101 °C  (OK vs 125 °C)
  efficiency = 100 × 3.3 / 5.2  ≈ 63.46 %
"""
from __future__ import annotations

import math
import pytest

from kerf_electronics.ldo_dropout_check import (
    LDOSpec,
    LDODropoutReport,
    check_ldo_dropout,
    check_ldo_dropout_from_dict,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ref_spec(**overrides) -> LDOSpec:
    """Reference 5V→3.3V LDO spec with optional overrides."""
    defaults = dict(
        V_out_V=3.3,
        V_in_min_V=4.8,
        V_in_max_V=5.2,
        I_load_A=0.5,
        dropout_voltage_at_max_load_mV=200.0,
        junction_to_ambient_thermal_resistance_K_per_W=80.0,
        T_ambient_C=25.0,
        T_max_junction_C=125.0,
    )
    defaults.update(overrides)
    return LDOSpec(**defaults)


# ── Test 1: Reference case — all compliant ────────────────────────────────────

class TestReferenceCase:
    """5V→3.3V nominal case: headroom 1500mV, P=0.95W, Tj=101°C — all pass."""

    def setup_method(self):
        self.report = check_ldo_dropout(_ref_spec())

    def test_headroom_value(self):
        assert self.report.headroom_min_mV == pytest.approx(1500.0, abs=0.01)

    def test_dropout_compliant(self):
        assert self.report.dropout_compliant is True

    def test_power_dissipation(self):
        # P = (5.2 - 3.3) × 0.5 = 1.9 × 0.5 = 0.95 W
        assert self.report.power_dissipation_W == pytest.approx(0.95, abs=1e-6)

    def test_junction_temp(self):
        # T_j = 25 + 0.95 × 80 = 25 + 76 = 101 °C
        assert self.report.junction_temp_estimate_C == pytest.approx(101.0, abs=0.01)

    def test_thermal_compliant(self):
        assert self.report.thermal_compliant is True

    def test_efficiency(self):
        # efficiency = 100 × 3.3 / 5.2
        expected = 100.0 * 3.3 / 5.2
        assert self.report.efficiency_pct == pytest.approx(expected, rel=1e-5)

    def test_honest_caveat_present(self):
        caveat = self.report.honest_caveat
        assert "quiescent" in caveat.lower() or "I_Q" in caveat
        assert "transient" in caveat.lower()
        assert "stability" in caveat.lower() or "capacitor" in caveat.lower()


# ── Test 2: Marginal headroom — just barely below dropout spec ────────────────

class TestMarginalHeadroom:
    """V_in_min gives 199mV headroom on a 200mV-dropout LDO — non-compliant."""

    def setup_method(self):
        # headroom = (3.499 - 3.3) × 1000 ≈ 199 mV < 200 mV dropout spec → FAIL
        # Use clean integers to avoid floating-point ambiguity:
        # V_out=1.0, V_in_min=1.199, dropout=200mV → headroom ≈ 199 mV < 200 mV
        self.report = check_ldo_dropout(LDOSpec(
            V_out_V=1.0,
            V_in_min_V=1.199,
            V_in_max_V=1.5,
            I_load_A=0.5,
            dropout_voltage_at_max_load_mV=200.0,
            junction_to_ambient_thermal_resistance_K_per_W=80.0,
            T_ambient_C=25.0,
            T_max_junction_C=125.0,
        ))

    def test_headroom_value(self):
        # headroom ≈ 199 mV
        assert self.report.headroom_min_mV == pytest.approx(199.0, abs=1.0)

    def test_dropout_not_compliant(self):
        # headroom (≈199 mV) < dropout spec (200 mV) → non-compliant
        assert self.report.dropout_compliant is False

    def test_caveat_mentions_fail(self):
        assert "FAIL" in self.report.honest_caveat or "dropout" in self.report.honest_caveat.lower()


# ── Test 3: Dropout failure — headroom below dropout spec ─────────────────────

class TestDropoutFail:
    """V_in_min gives only 100mV headroom on a 200mV-dropout LDO — clear failure."""

    def setup_method(self):
        # headroom = (3.4 - 3.3) × 1000 = 100 mV < 200 mV dropout spec
        self.report = check_ldo_dropout(_ref_spec(V_in_min_V=3.4))

    def test_headroom_value(self):
        assert self.report.headroom_min_mV == pytest.approx(100.0, abs=0.01)

    def test_dropout_not_compliant(self):
        assert self.report.dropout_compliant is False

    def test_thermal_still_reported(self):
        # Thermal check independent of dropout check
        assert isinstance(self.report.thermal_compliant, bool)


# ── Test 4: Thermal failure — heavy load pushes T_j over limit ────────────────

class TestThermalFail:
    """High load current and tight thermal resistance → T_j > 125°C."""

    def setup_method(self):
        # P = (12.0 - 3.3) × 1.5 = 8.7 × 1.5 = 13.05 W
        # T_j = 25 + 13.05 × 15 = 25 + 195.75 = 220.75 °C  > 125 °C → FAIL
        self.spec = LDOSpec(
            V_out_V=3.3,
            V_in_min_V=11.0,
            V_in_max_V=12.0,
            I_load_A=1.5,
            dropout_voltage_at_max_load_mV=400.0,
            junction_to_ambient_thermal_resistance_K_per_W=15.0,
            T_ambient_C=25.0,
            T_max_junction_C=125.0,
        )
        self.report = check_ldo_dropout(self.spec)

    def test_power_dissipation(self):
        expected_P = (12.0 - 3.3) * 1.5  # = 13.05 W
        assert self.report.power_dissipation_W == pytest.approx(expected_P, rel=1e-5)

    def test_junction_temp(self):
        expected_T = 25.0 + (12.0 - 3.3) * 1.5 * 15.0  # = 220.75 °C
        assert self.report.junction_temp_estimate_C == pytest.approx(expected_T, rel=1e-5)

    def test_thermal_not_compliant(self):
        assert self.report.thermal_compliant is False

    def test_dropout_still_compliant(self):
        # headroom = (11.0 - 3.3) × 1000 = 7700 mV >> 400 mV dropout
        assert self.report.dropout_compliant is True

    def test_caveat_mentions_thermal_fail(self):
        assert "FAIL" in self.report.honest_caveat or "thermal" in self.report.honest_caveat.lower()


# ── Test 5: Both failures simultaneously ─────────────────────────────────────

class TestBothFails:
    """Low V_in_min AND high power → both dropout and thermal fail."""

    def setup_method(self):
        # V_in_min too low: headroom = (3.35 - 3.3) × 1000 = 50 mV < 200 mV
        # V_in_max high: P = (12.0 - 3.3) × 1.0 = 8.7 W → T_j = 25 + 8.7 × 80 = 721 °C
        self.report = check_ldo_dropout(LDOSpec(
            V_out_V=3.3,
            V_in_min_V=3.35,
            V_in_max_V=12.0,
            I_load_A=1.0,
            dropout_voltage_at_max_load_mV=200.0,
            junction_to_ambient_thermal_resistance_K_per_W=80.0,
            T_ambient_C=25.0,
            T_max_junction_C=125.0,
        ))

    def test_dropout_not_compliant(self):
        assert self.report.dropout_compliant is False

    def test_thermal_not_compliant(self):
        assert self.report.thermal_compliant is False


# ── Test 6: High-efficiency (near-zero dropout) case ──────────────────────────

class TestHighEfficiency:
    """1.1V→1.0V (100mV headroom) LDO — tight but valid spec."""

    def setup_method(self):
        # headroom = (1.1 - 1.0) × 1000 = 100 mV > 80 mV dropout spec
        # P = (1.2 - 1.0) × 2.0 = 0.4 W
        # T_j = 70 + 0.4 × 40 = 70 + 16 = 86 °C < 125 °C
        self.report = check_ldo_dropout(LDOSpec(
            V_out_V=1.0,
            V_in_min_V=1.1,
            V_in_max_V=1.2,
            I_load_A=2.0,
            dropout_voltage_at_max_load_mV=80.0,
            junction_to_ambient_thermal_resistance_K_per_W=40.0,
            T_ambient_C=70.0,
            T_max_junction_C=125.0,
        ))

    def test_headroom(self):
        assert self.report.headroom_min_mV == pytest.approx(100.0, abs=0.01)

    def test_dropout_compliant(self):
        assert self.report.dropout_compliant is True

    def test_junction_temp(self):
        assert self.report.junction_temp_estimate_C == pytest.approx(86.0, abs=0.01)

    def test_thermal_compliant(self):
        assert self.report.thermal_compliant is True

    def test_efficiency_near_83pct(self):
        # efficiency = 100 × 1.0 / 1.2 ≈ 83.33%
        assert self.report.efficiency_pct == pytest.approx(100.0 * 1.0 / 1.2, rel=1e-5)


# ── Test 7: Automotive case — 150°C Tj limit ──────────────────────────────────

class TestAutomotiveJTemp:
    """AEC-Q100 automotive LDO with 150°C max junction temperature."""

    def setup_method(self):
        # P = (14.0 - 5.0) × 0.2 = 1.8 W
        # T_j = 85 + 1.8 × 30 = 85 + 54 = 139 °C < 150 → pass
        self.report = check_ldo_dropout(LDOSpec(
            V_out_V=5.0,
            V_in_min_V=7.0,
            V_in_max_V=14.0,
            I_load_A=0.2,
            dropout_voltage_at_max_load_mV=500.0,
            junction_to_ambient_thermal_resistance_K_per_W=30.0,
            T_ambient_C=85.0,
            T_max_junction_C=150.0,
        ))

    def test_power_dissipation(self):
        # P = (14 - 5) × 0.2 = 1.8 W
        assert self.report.power_dissipation_W == pytest.approx(1.8, rel=1e-5)

    def test_junction_temp(self):
        # T_j = 85 + 1.8 × 30 = 85 + 54 = 139 °C
        assert self.report.junction_temp_estimate_C == pytest.approx(139.0, abs=0.01)

    def test_thermal_compliant_vs_150C(self):
        assert self.report.thermal_compliant is True


# ── Test 8: V_in_min == V_in_max (single voltage rail) ───────────────────────

class TestSingleInputVoltage:
    """V_in_min == V_in_max: valid; headroom and P_diss computed consistently."""

    def setup_method(self):
        # V_in = 5.0 exactly; headroom = (5.0 - 3.3) × 1000 = 1700 mV
        # P = (5.0 - 3.3) × 0.3 = 0.51 W
        self.report = check_ldo_dropout(LDOSpec(
            V_out_V=3.3,
            V_in_min_V=5.0,
            V_in_max_V=5.0,
            I_load_A=0.3,
            dropout_voltage_at_max_load_mV=200.0,
            junction_to_ambient_thermal_resistance_K_per_W=100.0,
            T_ambient_C=25.0,
            T_max_junction_C=125.0,
        ))

    def test_headroom(self):
        assert self.report.headroom_min_mV == pytest.approx(1700.0, abs=0.01)

    def test_power_dissipation(self):
        assert self.report.power_dissipation_W == pytest.approx(0.51, rel=1e-5)

    def test_compliant(self):
        assert self.report.dropout_compliant is True


# ── Test 9: Efficiency values are reasonable ─────────────────────────────────

class TestEfficiencyBounds:
    """Efficiency must be in (0, 100] and equal V_out/V_in_max × 100."""

    @pytest.mark.parametrize("V_in_max,V_out", [
        (5.0, 3.3),
        (12.0, 5.0),
        (3.3, 1.8),
        (2.0, 1.2),  # V_in_min = 1.2 + 0.5 = 1.7 < V_in_max=2.0 → valid
    ])
    def test_efficiency_formula(self, V_in_max, V_out):
        spec = LDOSpec(
            V_out_V=V_out,
            V_in_min_V=V_out + 0.5,
            V_in_max_V=V_in_max,
            I_load_A=0.1,
            dropout_voltage_at_max_load_mV=100.0,
            junction_to_ambient_thermal_resistance_K_per_W=50.0,
        )
        report = check_ldo_dropout(spec)
        expected = 100.0 * V_out / V_in_max
        assert report.efficiency_pct == pytest.approx(expected, rel=1e-5)
        assert 0 < report.efficiency_pct <= 100.0


# ── Test 10: Input validation — bad inputs raise ValueError ──────────────────

class TestInputValidation:
    """Invalid inputs must raise ValueError with informative messages."""

    def test_zero_V_out(self):
        with pytest.raises(ValueError, match="V_out_V"):
            check_ldo_dropout(_ref_spec(V_out_V=0.0))

    def test_V_in_min_below_V_out(self):
        with pytest.raises(ValueError, match="V_in_min_V"):
            check_ldo_dropout(_ref_spec(V_in_min_V=3.0, V_out_V=3.3))

    def test_V_in_max_below_V_in_min(self):
        with pytest.raises(ValueError, match="V_in_max_V"):
            check_ldo_dropout(_ref_spec(V_in_min_V=5.0, V_in_max_V=4.5))

    def test_zero_I_load(self):
        with pytest.raises(ValueError, match="I_load_A"):
            check_ldo_dropout(_ref_spec(I_load_A=0.0))

    def test_zero_dropout_spec(self):
        with pytest.raises(ValueError, match="dropout_voltage"):
            check_ldo_dropout(_ref_spec(dropout_voltage_at_max_load_mV=0.0))

    def test_zero_theta_ja(self):
        with pytest.raises(ValueError, match="thermal_resistance"):
            check_ldo_dropout(
                _ref_spec(junction_to_ambient_thermal_resistance_K_per_W=0.0)
            )

    def test_T_max_below_T_ambient(self):
        with pytest.raises(ValueError, match="T_max_junction"):
            check_ldo_dropout(_ref_spec(T_ambient_C=30.0, T_max_junction_C=25.0))


# ── Test 11: Dict interface ───────────────────────────────────────────────────

class TestDictInterface:
    """check_ldo_dropout_from_dict returns {ok: True, ...} for valid inputs."""

    def test_valid_dict(self):
        d = dict(
            V_out_V=3.3,
            V_in_min_V=4.8,
            V_in_max_V=5.2,
            I_load_A=0.5,
            dropout_voltage_at_max_load_mV=200.0,
            junction_to_ambient_thermal_resistance_K_per_W=80.0,
        )
        result = check_ldo_dropout_from_dict(d)
        assert result["ok"] is True
        assert result["headroom_min_mV"] == pytest.approx(1500.0, abs=0.01)
        assert result["dropout_compliant"] is True
        assert result["power_dissipation_W"] == pytest.approx(0.95, rel=1e-5)
        assert result["junction_temp_estimate_C"] == pytest.approx(101.0, abs=0.01)
        assert result["thermal_compliant"] is True

    def test_missing_required_key(self):
        d = dict(V_out_V=3.3, V_in_min_V=4.8, V_in_max_V=5.2)
        result = check_ldo_dropout_from_dict(d)
        assert result["ok"] is False
        assert "reason" in result

    def test_invalid_value_type(self):
        d = dict(
            V_out_V="bad",
            V_in_min_V=4.8,
            V_in_max_V=5.2,
            I_load_A=0.5,
            dropout_voltage_at_max_load_mV=200.0,
            junction_to_ambient_thermal_resistance_K_per_W=80.0,
        )
        result = check_ldo_dropout_from_dict(d)
        assert result["ok"] is False

    def test_optional_T_defaults(self):
        """Default T_ambient=25, T_max=125 are applied when not in dict."""
        d = dict(
            V_out_V=3.3,
            V_in_min_V=4.8,
            V_in_max_V=5.2,
            I_load_A=0.5,
            dropout_voltage_at_max_load_mV=200.0,
            junction_to_ambient_thermal_resistance_K_per_W=80.0,
        )
        result = check_ldo_dropout_from_dict(d)
        assert result["ok"] is True
        assert result["junction_temp_estimate_C"] == pytest.approx(101.0, abs=0.01)


# ── Test 12: Report is an LDODropoutReport dataclass ─────────────────────────

class TestReportType:
    def test_return_type(self):
        report = check_ldo_dropout(_ref_spec())
        assert isinstance(report, LDODropoutReport)

    def test_all_fields_present(self):
        report = check_ldo_dropout(_ref_spec())
        assert hasattr(report, "headroom_min_mV")
        assert hasattr(report, "dropout_compliant")
        assert hasattr(report, "power_dissipation_W")
        assert hasattr(report, "junction_temp_estimate_C")
        assert hasattr(report, "thermal_compliant")
        assert hasattr(report, "efficiency_pct")
        assert hasattr(report, "honest_caveat")

    def test_booleans_are_bool(self):
        report = check_ldo_dropout(_ref_spec())
        assert isinstance(report.dropout_compliant, bool)
        assert isinstance(report.thermal_compliant, bool)


# ── Test 13: TOOLS export exists ──────────────────────────────────────────────

class TestToolsExport:
    def test_tools_list_present(self):
        from kerf_electronics.ldo_dropout_check import TOOLS
        assert len(TOOLS) >= 1

    def test_tool_name(self):
        from kerf_electronics.ldo_dropout_check import TOOLS
        names = [t[0] for t in TOOLS]
        assert "electronics_check_ldo_dropout" in names


# ── Test 14: Re-export from kerf_electronics ─────────────────────────────────

class TestReExport:
    def test_ldospec_importable(self):
        from kerf_electronics import LDOSpec as _LDOSpec
        assert _LDOSpec is LDOSpec

    def test_ldo_report_importable(self):
        from kerf_electronics import LDODropoutReport as _R
        assert _R is LDODropoutReport

    def test_check_fn_importable(self):
        from kerf_electronics import check_ldo_dropout as _fn
        assert _fn is check_ldo_dropout
