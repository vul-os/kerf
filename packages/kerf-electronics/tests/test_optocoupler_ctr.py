"""
Tests for kerf_electronics.optocoupler_ctr — Optocoupler isolation circuit analysis.

Coverage:
  - 4N35-like (IF=10mA, CTR_min=100%, CTR_typ=300%, CTR_max=600%): IC oracles
  - PC817 (CTR 50–600%): wide range; saturation check with R_L=4.7k, Vcc=5V
  - HCPL-2611 high-speed: t_rise scales with R_L change
  - Marginal saturation (IF=2mA, R_L=10k, CTR_min=50%) — saturates but slow
  - Failed saturation (IF=1mA, CTR_min=20%, IC_sat=2mA) — NOT saturated
  - Warnings: IF over-limit, low headroom, not saturated, IF mismatch
  - Dict wrapper ok/error paths
  - LLM tool handler (asyncio)
  - Report field types and constraints
  - Vout_low / Vout_high correctness
  - t_rise RC model vs datasheet scaling
  - Validation errors
  - 12+ tests total (many more below)
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_electronics.optocoupler_ctr import (
    OptocouplerSpec,
    CircuitSpec,
    OptocouplerReport,
    analyze_optocoupler,
    analyze_optocoupler_from_dict,
    elec_analyze_optocoupler,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class FakeCtx:
    pass


# ── Standard 4N35-like device ─────────────────────────────────────────────────


class Test4N35Like:
    """
    4N35-like: IF=10mA, CTR_min=100%, CTR_typ=300%, CTR_max=600%
    R_pullup=1kΩ, Vcc=5V, C_load=20pF, Vce_sat=0.2V
    IC_min = 100/100 × 10 = 10 mA
    IC_typ = 300/100 × 10 = 30 mA
    IC_max = 600/100 × 10 = 60 mA
    IC_sat = 5V / 1000Ω × 1000 = 5 mA
    headroom = 10/5 = 2.0
    saturated = True
    """

    def setup_method(self):
        self.opto = OptocouplerSpec(
            model="4N35",
            IF_mA=10.0,
            CTR_min_percent=100.0,
            CTR_typ_percent=300.0,
            CTR_max_percent=600.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
            Vf_typ_V=1.2,
            t_rise_us_at_Rl=(2.0, 1000.0),
        )
        self.circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=1000.0,
            C_load_pF=20.0,
            R_LED_series_ohm=390.0,
            V_LED_drive_V=5.0,
        )
        self.report = analyze_optocoupler(self.opto, self.circuit)

    def test_IC_min_10mA(self):
        assert abs(self.report.IC_min_mA - 10.0) < 1e-6

    def test_IC_typ_30mA(self):
        assert abs(self.report.IC_typ_mA - 30.0) < 1e-6

    def test_IC_max_60mA(self):
        assert abs(self.report.IC_max_mA - 60.0) < 1e-6

    def test_IC_sat_5mA(self):
        expected = 5.0 / 1000.0 * 1000.0  # = 5 mA
        assert abs(self.report.IC_saturation_mA - expected) < 1e-6

    def test_saturated_true(self):
        assert self.report.saturated_min_case is True

    def test_headroom_2x(self):
        assert abs(self.report.headroom_factor_min - 2.0) < 1e-6

    def test_vout_low_is_vce_sat(self):
        assert abs(self.report.Vout_low_V - 0.2) < 1e-9

    def test_vout_high_is_vcc(self):
        assert abs(self.report.Vout_high_V - 5.0) < 1e-9

    def test_returns_dataclass(self):
        assert isinstance(self.report, OptocouplerReport)

    def test_warnings_list(self):
        assert isinstance(self.report.warnings, list)

    def test_honest_caveat_present(self):
        caveat = self.report.honest_caveat
        assert len(caveat) > 100
        assert "HONEST" in caveat or "linear" in caveat.lower() or "CTR" in caveat


# ── PC817 wide-range device ───────────────────────────────────────────────────


class TestPC817Saturation:
    """
    PC817: IF=10mA, CTR_min=50%, CTR_typ=200%, CTR_max=600%
    R_pullup=4700Ω, Vcc=5V
    IC_sat = 5/4700 × 1000 = 1.0638 mA
    IC_min = 50/100 × 10 = 5 mA
    5.0 >= 1.0638 → saturated
    headroom = 5.0 / 1.0638 ≈ 4.70
    """

    def setup_method(self):
        self.opto = OptocouplerSpec(
            model="PC817",
            IF_mA=10.0,
            CTR_min_percent=50.0,
            CTR_typ_percent=200.0,
            CTR_max_percent=600.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )
        self.circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=4700.0,
            C_load_pF=20.0,
            R_LED_series_ohm=330.0,
            V_LED_drive_V=5.0,
        )
        self.report = analyze_optocoupler(self.opto, self.circuit)

    def test_IC_min_5mA(self):
        assert abs(self.report.IC_min_mA - 5.0) < 1e-6

    def test_IC_sat_approx_1p06mA(self):
        expected = 5.0 / 4700.0 * 1000.0
        assert abs(self.report.IC_saturation_mA - expected) < 1e-4

    def test_saturated_true(self):
        """IC_min (5 mA) >> IC_sat (1.06 mA) → saturated."""
        assert self.report.saturated_min_case is True

    def test_headroom_gt_4(self):
        assert self.report.headroom_factor_min > 4.0

    def test_IC_max_60mA(self):
        assert abs(self.report.IC_max_mA - 60.0) < 1e-6

    def test_IC_typ_20mA(self):
        assert abs(self.report.IC_typ_mA - 20.0) < 1e-6


# ── HCPL-2611 high-speed: t_rise scales with R_L ─────────────────────────────


class TestHCPL2611RiseTimeScaling:
    """
    HCPL-2611: t_rise_spec = 0.06 µs at R_L_spec = 1000 Ω
    At R_L_actual = 2000 Ω → t_rise_scaled = 0.06 × 2 = 0.12 µs
    At R_L_actual = 500 Ω  → t_rise_scaled = 0.06 × 0.5 = 0.03 µs
    """

    def _make_opto(self):
        return OptocouplerSpec(
            model="HCPL-2611",
            IF_mA=10.0,
            CTR_min_percent=15.0,
            CTR_typ_percent=40.0,
            CTR_max_percent=150.0,
            Vce_sat_V=0.6,
            IF_max_mA=25.0,
            t_rise_us_at_Rl=(0.06, 1000.0),
        )

    def _make_circuit(self, R_pullup_ohm: float) -> CircuitSpec:
        return CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=R_pullup_ohm,
            C_load_pF=5.0,
            R_LED_series_ohm=200.0,
            V_LED_drive_V=5.0,
        )

    def test_t_rise_doubles_when_R_doubles(self):
        r1 = analyze_optocoupler(self._make_opto(), self._make_circuit(1000.0))
        r2 = analyze_optocoupler(self._make_opto(), self._make_circuit(2000.0))
        # At R=1000 Ω: t_rise_scaled = 0.06 µs; RC = 2.2×1000×5e-12×1e6 = 0.011 µs
        # t_rise = max(0.011, 0.06) = 0.06 µs
        # At R=2000 Ω: t_rise_scaled = 0.12 µs; RC = 0.022 µs → t_rise=0.12 µs
        # ratio should be 2.0
        ratio = r2.t_rise_us / r1.t_rise_us
        assert abs(ratio - 2.0) < 0.05, f"Expected ratio~2.0 got {ratio}"

    def test_t_rise_halves_when_R_halves(self):
        r1 = analyze_optocoupler(self._make_opto(), self._make_circuit(1000.0))
        r2 = analyze_optocoupler(self._make_opto(), self._make_circuit(500.0))
        ratio = r2.t_rise_us / r1.t_rise_us
        # At R=500 Ω: t_rise_scaled = 0.03 µs; RC = 0.0055 µs → max = 0.03
        assert abs(ratio - 0.5) < 0.05, f"Expected ratio~0.5 got {ratio}"

    def test_t_rise_at_spec_R(self):
        r = analyze_optocoupler(self._make_opto(), self._make_circuit(1000.0))
        # t_rise_scaled = 0.06; RC at C=5pF, R=1kΩ = 2.2×1000×5e-12×1e6=0.011 µs
        assert abs(r.t_rise_us - 0.06) < 1e-6

    def test_t_fall_equals_t_rise(self):
        r = analyze_optocoupler(self._make_opto(), self._make_circuit(1000.0))
        assert r.t_rise_us == r.t_fall_us


# ── Marginal saturation — saturated but slow ──────────────────────────────────


class TestMarginalSaturation:
    """
    IF=2mA, R_L=10kΩ, CTR_min=50%, Vcc=5V, C_load=100pF
    IC_min = 50/100 × 2 = 1.0 mA
    IC_sat = 5/10000 × 1000 = 0.5 mA
    headroom = 1.0/0.5 = 2.0
    saturated = True (but low headroom)
    t_rise (RC only) = 2.2 × 10000 × 100e-12 × 1e6 = 2.2 µs
    """

    def setup_method(self):
        self.opto = OptocouplerSpec(
            model="PC817-marginal",
            IF_mA=2.0,
            CTR_min_percent=50.0,
            CTR_typ_percent=150.0,
            CTR_max_percent=300.0,
            Vce_sat_V=0.15,
            IF_max_mA=50.0,
            t_rise_us_at_Rl=(0.0, 1000.0),  # no datasheet spec → RC only
        )
        self.circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=10000.0,
            C_load_pF=100.0,
            R_LED_series_ohm=1500.0,
            V_LED_drive_V=5.0,
        )
        self.report = analyze_optocoupler(self.opto, self.circuit)

    def test_IC_min_1mA(self):
        assert abs(self.report.IC_min_mA - 1.0) < 1e-6

    def test_IC_sat_0p5mA(self):
        assert abs(self.report.IC_saturation_mA - 0.5) < 1e-6

    def test_saturated_true(self):
        assert self.report.saturated_min_case is True

    def test_headroom_2x(self):
        assert abs(self.report.headroom_factor_min - 2.0) < 1e-6

    def test_t_rise_RC_dominated(self):
        # RC = 2.2 × 10000 × 100e-12 × 1e6 = 2.2 µs
        expected_RC = 2.2 * 10000.0 * 100e-12 * 1e6
        assert abs(self.report.t_rise_us - expected_RC) < 1e-6


# ── Failed saturation ─────────────────────────────────────────────────────────


class TestFailedSaturation:
    """
    IF=1mA, CTR_min=20%, CTR_typ=60%
    R_pullup=2200Ω, Vcc=4.4V
    IC_sat = 4.4/2200 × 1000 = 2.0 mA
    IC_min = 20/100 × 1 = 0.2 mA
    0.2 < 2.0 → NOT saturated
    headroom = 0.2/2.0 = 0.1 (< 1.0 → not saturated)
    """

    def setup_method(self):
        self.opto = OptocouplerSpec(
            model="test-marginal",
            IF_mA=1.0,
            CTR_min_percent=20.0,
            CTR_typ_percent=60.0,
            CTR_max_percent=200.0,
            Vce_sat_V=0.3,
            IF_max_mA=60.0,
        )
        self.circuit = CircuitSpec(
            Vcc_out_V=4.4,
            R_pullup_ohm=2200.0,
            C_load_pF=20.0,
            R_LED_series_ohm=4700.0,
            V_LED_drive_V=5.0,
        )
        self.report = analyze_optocoupler(self.opto, self.circuit)

    def test_saturated_false(self):
        assert self.report.saturated_min_case is False

    def test_IC_min_0p2mA(self):
        assert abs(self.report.IC_min_mA - 0.2) < 1e-6

    def test_IC_sat_2mA(self):
        expected = 4.4 / 2200.0 * 1000.0
        assert abs(self.report.IC_saturation_mA - expected) < 1e-6

    def test_headroom_lt_1(self):
        assert self.report.headroom_factor_min < 1.0

    def test_warning_not_saturated(self):
        warnings_text = " ".join(self.report.warnings)
        assert "NOT SATURATED" in warnings_text or "saturated" in warnings_text.lower()

    def test_warning_mentions_R_L_or_CTR(self):
        """Warning should suggest actionable fix."""
        warnings_text = " ".join(self.report.warnings)
        assert any(kw in warnings_text for kw in ["R_L", "CTR", "IF", "reduce", "increase"])


# ── Over-drive warning ────────────────────────────────────────────────────────


class TestOverDriveWarning:
    """IF > IF_max triggers warning."""

    def test_overdriven_if_warns(self):
        opto = OptocouplerSpec(
            model="PC817",
            IF_mA=80.0,   # > IF_max = 50 mA
            CTR_min_percent=50.0,
            CTR_typ_percent=200.0,
            CTR_max_percent=600.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=1000.0,
            C_load_pF=20.0,
            R_LED_series_ohm=100.0,
            V_LED_drive_V=12.0,
        )
        report = analyze_optocoupler(opto, circuit)
        warnings_text = " ".join(report.warnings)
        assert "IF_max" in warnings_text or "exceed" in warnings_text.lower()

    def test_normal_if_no_overdrive_warning(self):
        opto = OptocouplerSpec(
            model="PC817",
            IF_mA=10.0,
            CTR_min_percent=50.0,
            CTR_typ_percent=200.0,
            CTR_max_percent=600.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=1000.0,
            C_load_pF=20.0,
            R_LED_series_ohm=390.0,
            V_LED_drive_V=5.0,
        )
        report = analyze_optocoupler(opto, circuit)
        # No IF over-limit warning
        warnings_text = " ".join(report.warnings)
        assert "IF_max" not in warnings_text


# ── Low headroom warning ──────────────────────────────────────────────────────


class TestLowHeadroomWarning:
    """
    headroom < 2.0 but still saturated → headroom warning emitted.
    IC_min = 1.5 mA, IC_sat = 1.0 mA → headroom = 1.5 → warning
    """

    def test_low_headroom_triggers_warning(self):
        # IC_min = 15/100 × 10 = 1.5 mA
        # IC_sat = 5/5000 × 1000 = 1.0 mA
        # headroom = 1.5
        opto = OptocouplerSpec(
            model="test-lowheadroom",
            IF_mA=10.0,
            CTR_min_percent=15.0,
            CTR_typ_percent=40.0,
            CTR_max_percent=100.0,
            Vce_sat_V=0.2,
            IF_max_mA=60.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=5000.0,
            C_load_pF=20.0,
            R_LED_series_ohm=0.0,
            V_LED_drive_V=0.0,
        )
        report = analyze_optocoupler(opto, circuit)
        assert report.saturated_min_case is True
        assert report.headroom_factor_min < 2.0
        warnings_text = " ".join(report.warnings)
        assert "headroom" in warnings_text.lower() or "low" in warnings_text.lower()


# ── RC timing model ───────────────────────────────────────────────────────────


class TestRCTimingModel:
    """RC-only timing (no datasheet spec)."""

    def _opto(self, t_rise_us=0.0):
        return OptocouplerSpec(
            model="test",
            IF_mA=10.0,
            CTR_min_percent=100.0,
            CTR_typ_percent=200.0,
            CTR_max_percent=400.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
            t_rise_us_at_Rl=(t_rise_us, 1000.0),
        )

    def test_RC_formula_100pF(self):
        circuit = CircuitSpec(
            Vcc_out_V=3.3,
            R_pullup_ohm=4700.0,
            C_load_pF=100.0,
            R_LED_series_ohm=0.0,
            V_LED_drive_V=0.0,
        )
        report = analyze_optocoupler(self._opto(), circuit)
        expected_us = 2.2 * 4700.0 * 100e-12 * 1e6
        assert abs(report.t_rise_us - expected_us) < 1e-6

    def test_zero_capacitance_gives_zero_RC(self):
        circuit = CircuitSpec(
            Vcc_out_V=3.3,
            R_pullup_ohm=1000.0,
            C_load_pF=0.0,
            R_LED_series_ohm=0.0,
            V_LED_drive_V=0.0,
        )
        report = analyze_optocoupler(self._opto(), circuit)
        # RC = 0; no datasheet spec → t_rise = 0
        assert report.t_rise_us == 0.0

    def test_datasheet_spec_dominates_RC(self):
        # RC = 2.2 × 1000 × 1e-12 = 0.0022 µs (very small at C=1pF)
        # Datasheet spec = 5 µs at R_spec=1kΩ → t_rise = 5 µs
        opto = self._opto(t_rise_us=5.0)
        circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=1000.0,
            C_load_pF=1.0,
            R_LED_series_ohm=0.0,
            V_LED_drive_V=0.0,
        )
        report = analyze_optocoupler(opto, circuit)
        assert abs(report.t_rise_us - 5.0) < 1e-6


# ── Validation errors ─────────────────────────────────────────────────────────


class TestValidationErrors:
    """Invalid inputs raise ValueError."""

    def _good_circuit(self):
        return CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=1000.0,
            C_load_pF=20.0,
            R_LED_series_ohm=390.0,
            V_LED_drive_V=5.0,
        )

    def _good_opto(self):
        return OptocouplerSpec(
            model="4N35",
            IF_mA=10.0,
            CTR_min_percent=100.0,
            CTR_typ_percent=300.0,
            CTR_max_percent=600.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )

    def test_negative_IF(self):
        opto = self._good_opto()
        opto.IF_mA = -1.0
        with pytest.raises(ValueError, match="IF_mA"):
            analyze_optocoupler(opto, self._good_circuit())

    def test_negative_CTR_min(self):
        opto = self._good_opto()
        opto.CTR_min_percent = -5.0
        with pytest.raises(ValueError, match="CTR_min_percent"):
            analyze_optocoupler(opto, self._good_circuit())

    def test_CTR_typ_lt_min(self):
        opto = self._good_opto()
        opto.CTR_typ_percent = 50.0  # < CTR_min=100
        with pytest.raises(ValueError, match="CTR_typ_percent"):
            analyze_optocoupler(opto, self._good_circuit())

    def test_CTR_max_lt_typ(self):
        opto = self._good_opto()
        opto.CTR_max_percent = 200.0  # < CTR_typ=300
        with pytest.raises(ValueError, match="CTR_max_percent"):
            analyze_optocoupler(opto, self._good_circuit())

    def test_negative_Vcc(self):
        circuit = self._good_circuit()
        circuit.Vcc_out_V = -1.0
        with pytest.raises(ValueError, match="Vcc_out_V"):
            analyze_optocoupler(self._good_opto(), circuit)

    def test_zero_R_pullup(self):
        circuit = self._good_circuit()
        circuit.R_pullup_ohm = 0.0
        with pytest.raises(ValueError, match="R_pullup_ohm"):
            analyze_optocoupler(self._good_opto(), circuit)

    def test_negative_C_load(self):
        circuit = self._good_circuit()
        circuit.C_load_pF = -1.0
        with pytest.raises(ValueError, match="C_load_pF"):
            analyze_optocoupler(self._good_opto(), circuit)


# ── Report fields ─────────────────────────────────────────────────────────────


class TestReportFields:
    """All report fields present, typed, and in valid ranges."""

    def setup_method(self):
        opto = OptocouplerSpec(
            model="PC817",
            IF_mA=5.0,
            CTR_min_percent=50.0,
            CTR_typ_percent=200.0,
            CTR_max_percent=600.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=3.3,
            R_pullup_ohm=2200.0,
            C_load_pF=50.0,
            R_LED_series_ohm=220.0,
            V_LED_drive_V=3.3,
        )
        self.report = analyze_optocoupler(opto, circuit)

    def test_IC_min_positive(self):
        assert self.report.IC_min_mA > 0

    def test_IC_typ_gte_IC_min(self):
        assert self.report.IC_typ_mA >= self.report.IC_min_mA

    def test_IC_max_gte_IC_typ(self):
        assert self.report.IC_max_mA >= self.report.IC_typ_mA

    def test_IC_sat_positive(self):
        assert self.report.IC_saturation_mA > 0

    def test_headroom_positive(self):
        assert self.report.headroom_factor_min > 0

    def test_t_rise_nonneg(self):
        assert self.report.t_rise_us >= 0

    def test_t_fall_nonneg(self):
        assert self.report.t_fall_us >= 0

    def test_vout_low_gte_zero(self):
        assert self.report.Vout_low_V >= 0

    def test_vout_high_equals_vcc(self):
        assert abs(self.report.Vout_high_V - 3.3) < 1e-9

    def test_saturated_is_bool(self):
        assert isinstance(self.report.saturated_min_case, bool)

    def test_warnings_is_list(self):
        assert isinstance(self.report.warnings, list)

    def test_caveat_is_string(self):
        assert isinstance(self.report.honest_caveat, str)
        assert len(self.report.honest_caveat) > 50


# ── Dict wrapper ───────────────────────────────────────────────────────────────


class TestDictWrapper:
    """analyze_optocoupler_from_dict ok/error paths."""

    def test_ok_path(self):
        result = analyze_optocoupler_from_dict({
            "model": "4N35",
            "IF_mA": 10.0,
            "CTR_min_percent": 100.0,
            "CTR_typ_percent": 300.0,
            "CTR_max_percent": 600.0,
            "IF_max_mA": 50.0,
            "Vcc_out_V": 5.0,
            "R_pullup_ohm": 1000.0,
        })
        assert result["ok"] is True
        assert abs(result["IC_min_mA"] - 10.0) < 1e-6
        assert abs(result["IC_typ_mA"] - 30.0) < 1e-6
        assert result["saturated_min_case"] is True

    def test_missing_required_field(self):
        result = analyze_optocoupler_from_dict({
            "model": "4N35",
            "IF_mA": 10.0,
            # missing CTR_min_percent etc.
        })
        assert result["ok"] is False
        assert "reason" in result

    def test_invalid_CTR_order(self):
        result = analyze_optocoupler_from_dict({
            "model": "bad",
            "IF_mA": 10.0,
            "CTR_min_percent": 300.0,  # > typ
            "CTR_typ_percent": 100.0,
            "CTR_max_percent": 600.0,
            "IF_max_mA": 50.0,
            "Vcc_out_V": 5.0,
            "R_pullup_ohm": 1000.0,
        })
        assert result["ok"] is False

    def test_optional_fields_defaults(self):
        result = analyze_optocoupler_from_dict({
            "IF_mA": 5.0,
            "CTR_min_percent": 50.0,
            "CTR_typ_percent": 100.0,
            "CTR_max_percent": 300.0,
            "IF_max_mA": 50.0,
            "Vcc_out_V": 5.0,
            "R_pullup_ohm": 1000.0,
        })
        assert result["ok"] is True
        # C_load default = 20 pF; t_rise from datasheet default (2.0µs @ 1kΩ)
        assert result["t_rise_us"] > 0

    def test_t_rise_at_rl_from_list(self):
        result = analyze_optocoupler_from_dict({
            "IF_mA": 10.0,
            "CTR_min_percent": 100.0,
            "CTR_typ_percent": 200.0,
            "CTR_max_percent": 400.0,
            "IF_max_mA": 50.0,
            "Vcc_out_V": 5.0,
            "R_pullup_ohm": 1000.0,
            "t_rise_us_at_Rl": [0.1, 500.0],
            "C_load_pF": 1.0,
        })
        assert result["ok"] is True
        # t_rise_scaled = 0.1 × (1000/500) = 0.2 µs
        assert abs(result["t_rise_us"] - 0.2) < 1e-6


# ── LLM tool handler ───────────────────────────────────────────────────────────


class TestLLMToolHandler:
    """Async LLM tool handler."""

    def test_ok_json(self):
        args = json.dumps({
            "model": "4N35",
            "IF_mA": 10.0,
            "CTR_min_percent": 100.0,
            "CTR_typ_percent": 300.0,
            "CTR_max_percent": 600.0,
            "IF_max_mA": 50.0,
            "Vcc_out_V": 5.0,
            "R_pullup_ohm": 1000.0,
        }).encode()
        result_str = _run(elec_analyze_optocoupler(FakeCtx(), args))
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert "IC_min_mA" in result
        assert "saturated_min_case" in result
        assert "honest_caveat" in result

    def test_bad_json(self):
        result_str = _run(elec_analyze_optocoupler(FakeCtx(), b"not json"))
        result = json.loads(result_str)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_spec(self):
        args = json.dumps({
            "IF_mA": -1.0,  # invalid
            "CTR_min_percent": 100.0,
            "CTR_typ_percent": 200.0,
            "CTR_max_percent": 400.0,
            "IF_max_mA": 50.0,
            "Vcc_out_V": 5.0,
            "R_pullup_ohm": 1000.0,
        }).encode()
        result_str = _run(elec_analyze_optocoupler(FakeCtx(), args))
        result = json.loads(result_str)
        assert "error" in result


# ── 3.3V CMOS interface ────────────────────────────────────────────────────────


class Test3V3CMOSInterface:
    """
    Real-world: HCPL-314J (gate-drive opto) at 3.3V CMOS logic output.
    IF=5mA, CTR_min=0.7 (70%), Vcc=15V, R_L=1kΩ
    IC_min = 70/100 × 5 = 3.5 mA
    IC_sat = 15/1000 × 1000 = 15 mA
    3.5 < 15 → NOT saturated
    """

    def test_gate_drive_not_saturated_with_low_if(self):
        opto = OptocouplerSpec(
            model="HCPL-314J",
            IF_mA=5.0,
            CTR_min_percent=70.0,
            CTR_typ_percent=150.0,
            CTR_max_percent=300.0,
            Vce_sat_V=1.5,
            IF_max_mA=25.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=15.0,
            R_pullup_ohm=1000.0,
            C_load_pF=100.0,
            R_LED_series_ohm=470.0,
            V_LED_drive_V=5.0,
        )
        report = analyze_optocoupler(opto, circuit)
        assert report.saturated_min_case is False
        assert report.headroom_factor_min < 1.0


# ── Headroom formula check ────────────────────────────────────────────────────


class TestHeadroomFormula:
    """Verify headroom_factor_min = IC_min / IC_sat exactly."""

    def test_headroom_formula_exact(self):
        opto = OptocouplerSpec(
            model="test",
            IF_mA=7.5,
            CTR_min_percent=80.0,
            CTR_typ_percent=200.0,
            CTR_max_percent=400.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=3.3,
            R_pullup_ohm=3300.0,
            C_load_pF=20.0,
            R_LED_series_ohm=0.0,
            V_LED_drive_V=0.0,
        )
        report = analyze_optocoupler(opto, circuit)
        IC_min_expected = 80.0 / 100.0 * 7.5  # = 6.0 mA
        IC_sat_expected = 3.3 / 3300.0 * 1000.0  # = 1.0 mA
        headroom_expected = IC_min_expected / IC_sat_expected  # = 6.0
        assert abs(report.IC_min_mA - IC_min_expected) < 1e-6
        assert abs(report.IC_saturation_mA - IC_sat_expected) < 1e-6
        assert abs(report.headroom_factor_min - headroom_expected) < 1e-6


# ── Saturation boundary (exactly at threshold) ────────────────────────────────


class TestSaturationBoundary:
    """IC_min exactly equals IC_sat → saturated (boundary case)."""

    def test_exactly_at_boundary_is_saturated(self):
        # IC_min = CTR_min/100 × IF = CTR_min/100 × 10
        # IC_sat = Vcc/R_pullup × 1000 = 5/5000×1000 = 1.0 mA
        # Set CTR_min=10% → IC_min = 1.0 mA → exactly equals IC_sat
        opto = OptocouplerSpec(
            model="test-boundary",
            IF_mA=10.0,
            CTR_min_percent=10.0,
            CTR_typ_percent=30.0,
            CTR_max_percent=100.0,
            Vce_sat_V=0.2,
            IF_max_mA=50.0,
        )
        circuit = CircuitSpec(
            Vcc_out_V=5.0,
            R_pullup_ohm=5000.0,
            C_load_pF=20.0,
            R_LED_series_ohm=0.0,
            V_LED_drive_V=0.0,
        )
        report = analyze_optocoupler(opto, circuit)
        assert abs(report.IC_min_mA - 1.0) < 1e-6
        assert abs(report.IC_saturation_mA - 1.0) < 1e-6
        assert report.saturated_min_case is True
        assert abs(report.headroom_factor_min - 1.0) < 1e-6
