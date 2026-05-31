"""
Tests for kerf_cam.rigid_tapping_check — rigid-tap operation validator.

References
----------
* Sandvik CoroPlus Technical Guide 2024 — rigid tapping torque coefficients
* Machinery's Handbook 31e §1934 — rigid tapping force/torque, F=pitch×rpm
* NIST RS-274/NGC §3.8.4 — G84/G74 rigid tapping coupling

Run:
    pytest packages/kerf-cam/tests/test_rigid_tapping_check.py -v
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cam.rigid_tapping_check import (
    RigidTapSpec,
    RigidTapReport,
    _parse_thread_size,
    check_rigid_tap,
    cam_check_rigid_tap_spec,
    run_cam_check_rigid_tap,
    _K_TABLE,
    _RPM_LIMIT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**kw) -> RigidTapSpec:
    """Return a RigidTapSpec with sensible defaults overrideable via kw."""
    defaults = dict(
        thread_size="M6x1.0",
        material="steel_1018",
        hole_depth_mm=15.0,
        spindle_rpm=500.0,
        machine_max_sync_rpm=4000,
        tap_tool_material="HSS",
    )
    defaults.update(kw)
    return RigidTapSpec(**defaults)


# ---------------------------------------------------------------------------
# 1. Thread size parser — metric
# ---------------------------------------------------------------------------

class TestParseThreadSizeMetric:
    def test_m6x1_lowercase(self):
        d, p = _parse_thread_size("M6x1.0")
        assert d == pytest.approx(6.0)
        assert p == pytest.approx(1.0)

    def test_m6x1_uppercase_x(self):
        d, p = _parse_thread_size("M6X1.0")
        assert d == pytest.approx(6.0)
        assert p == pytest.approx(1.0)

    def test_m10x1_5(self):
        d, p = _parse_thread_size("M10x1.5")
        assert d == pytest.approx(10.0)
        assert p == pytest.approx(1.5)

    def test_m4x0_7(self):
        d, p = _parse_thread_size("M4x0.7")
        assert d == pytest.approx(4.0)
        assert p == pytest.approx(0.7)

    def test_m3x0_5(self):
        d, p = _parse_thread_size("M3x0.5")
        assert d == pytest.approx(3.0)
        assert p == pytest.approx(0.5)

    def test_m16x2(self):
        d, p = _parse_thread_size("M16x2.0")
        assert d == pytest.approx(16.0)
        assert p == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 2. Thread size parser — inch UNC/UNF
# ---------------------------------------------------------------------------

class TestParseThreadSizeInch:
    def test_quarter_20_unc(self):
        # 1/4-20 UNC: d=0.25 in = 6.35 mm, pitch = 25.4/20 = 1.27 mm
        d, p = _parse_thread_size("1/4-20")
        assert d == pytest.approx(6.35, rel=1e-4)
        assert p == pytest.approx(25.4 / 20, rel=1e-4)

    def test_three_eighths_16(self):
        # 3/8-16 UNC: d=0.375 in = 9.525 mm
        d, p = _parse_thread_size("3/8-16")
        assert d == pytest.approx(9.525, rel=1e-4)
        assert p == pytest.approx(25.4 / 16, rel=1e-4)

    def test_half_13(self):
        # 1/2-13 UNC
        d, p = _parse_thread_size("1/2-13")
        assert d == pytest.approx(12.7, rel=1e-4)
        assert p == pytest.approx(25.4 / 13, rel=1e-4)

    def test_quarter_28_unf(self):
        # 1/4-28 UNF
        d, p = _parse_thread_size("1/4-28")
        assert d == pytest.approx(6.35, rel=1e-4)
        assert p == pytest.approx(25.4 / 28, rel=1e-4)


# ---------------------------------------------------------------------------
# 3. Thread size parser — error cases
# ---------------------------------------------------------------------------

class TestParseThreadSizeErrors:
    def test_bad_format_raises(self):
        with pytest.raises(ValueError, match="Unrecognised thread_size"):
            _parse_thread_size("banana")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_thread_size("")

    def test_metric_zero_pitch_raises(self):
        with pytest.raises(ValueError):
            _parse_thread_size("M6x0.0")


# ---------------------------------------------------------------------------
# 4. Core check — sync compliance
# ---------------------------------------------------------------------------

class TestSyncCompliance:
    def test_m6_steel_hss_500rpm_4000max_is_compliant(self):
        """Spec 1 from task: M6×1.0, steel, HSS, 500 rpm, machine_max=4000 → sync=True."""
        spec = _spec(
            thread_size="M6x1.0",
            material="steel_1018",
            hole_depth_mm=15.0,
            spindle_rpm=500.0,
            machine_max_sync_rpm=4000,
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        assert r.sync_compliant is True

    def test_m10_stainless_hss_6000rpm_4000max_not_compliant(self):
        """Spec 2 from task: M10×1.5, stainless, HSS, 6000 rpm vs machine_max=4000 → False."""
        spec = _spec(
            thread_size="M10x1.5",
            material="stainless_303",
            hole_depth_mm=20.0,
            spindle_rpm=6000.0,
            machine_max_sync_rpm=4000,
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        assert r.sync_compliant is False

    def test_rpm_exactly_at_max_is_compliant(self):
        spec = _spec(spindle_rpm=4000.0, machine_max_sync_rpm=4000)
        r = check_rigid_tap(spec)
        assert r.sync_compliant is True

    def test_rpm_one_above_max_not_compliant(self):
        spec = _spec(spindle_rpm=4001.0, machine_max_sync_rpm=4000)
        r = check_rigid_tap(spec)
        assert r.sync_compliant is False


# ---------------------------------------------------------------------------
# 5. Feed coupling F = pitch × rpm (MH 31e §1934)
# ---------------------------------------------------------------------------

class TestFeedCoupling:
    def test_m6x1_500rpm(self):
        """M6×1.0, 500 rpm → feed = 1.0 × 500 = 500 mm/min."""
        spec = _spec(thread_size="M6x1.0", spindle_rpm=500.0)
        r = check_rigid_tap(spec)
        assert r.computed_feed_mm_per_min == pytest.approx(500.0)

    def test_m10x1_5_600rpm(self):
        """M10×1.5, 600 rpm → feed = 1.5 × 600 = 900 mm/min."""
        spec = _spec(thread_size="M10x1.5", spindle_rpm=600.0)
        r = check_rigid_tap(spec)
        assert r.computed_feed_mm_per_min == pytest.approx(900.0)

    def test_m8x1_25_800rpm(self):
        """M8×1.25, 800 rpm → feed = 1000 mm/min."""
        spec = _spec(thread_size="M8x1.25", spindle_rpm=800.0)
        r = check_rigid_tap(spec)
        assert r.computed_feed_mm_per_min == pytest.approx(1000.0)

    def test_quarter_20_500rpm(self):
        """1/4-20 UNC, 500 rpm → feed = (25.4/20) × 500 = 635 mm/min."""
        spec = _spec(thread_size="1/4-20", spindle_rpm=500.0)
        r = check_rigid_tap(spec)
        expected = (25.4 / 20) * 500
        assert r.computed_feed_mm_per_min == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# 6. Torque model T = K · D³
# ---------------------------------------------------------------------------

class TestTorqueModel:
    def test_m6_steel_hss_torque(self):
        """M6 steel HSS: K=0.35, D=6 → T = 0.35 × 216 = 75.6 N·m."""
        spec = _spec(thread_size="M6x1.0", material="steel_1018", tap_tool_material="HSS")
        r = check_rigid_tap(spec)
        expected = 0.35 * (6.0 ** 3)
        assert r.recommended_torque_Nm == pytest.approx(expected, rel=1e-4)

    def test_m10_steel_hss_torque(self):
        """M10 steel HSS: K=0.35, D=10 → T = 0.35 × 1000 = 350 N·m."""
        spec = _spec(thread_size="M10x1.5", material="steel_1018", tap_tool_material="HSS")
        r = check_rigid_tap(spec)
        expected = 0.35 * (10.0 ** 3)
        assert r.recommended_torque_Nm == pytest.approx(expected, rel=1e-4)

    def test_aluminum_lower_torque_than_steel(self):
        """Aluminum vs steel: aluminum should produce lower torque (lower K)."""
        spec_steel = _spec(material="steel_1018",    tap_tool_material="HSS")
        spec_alum  = _spec(material="aluminum_6061", tap_tool_material="HSS")
        r_steel = check_rigid_tap(spec_steel)
        r_alum  = check_rigid_tap(spec_alum)
        assert r_alum.recommended_torque_Nm < r_steel.recommended_torque_Nm

    def test_carbide_lower_torque_than_hss_same_material(self):
        """HSS vs carbide: carbide has lower K → lower torque estimate."""
        spec_hss     = _spec(material="steel_1018", tap_tool_material="HSS")
        spec_carbide = _spec(material="steel_1018", tap_tool_material="carbide")
        r_hss     = check_rigid_tap(spec_hss)
        r_carbide = check_rigid_tap(spec_carbide)
        assert r_carbide.recommended_torque_Nm < r_hss.recommended_torque_Nm

    def test_cobalt_between_hss_and_carbide(self):
        """Cobalt K is between HSS and carbide → torque ordering."""
        spec_hss     = _spec(material="steel_1018", tap_tool_material="HSS")
        spec_cobalt  = _spec(material="steel_1018", tap_tool_material="cobalt")
        spec_carbide = _spec(material="steel_1018", tap_tool_material="carbide")
        r_hss     = check_rigid_tap(spec_hss)
        r_cobalt  = check_rigid_tap(spec_cobalt)
        r_carbide = check_rigid_tap(spec_carbide)
        assert r_carbide.recommended_torque_Nm < r_cobalt.recommended_torque_Nm < r_hss.recommended_torque_Nm

    def test_stainless_higher_torque_than_steel_hss(self):
        """Stainless 303 HSS K=0.50 > steel HSS K=0.35 → higher torque."""
        spec_steel = _spec(material="steel_1018",    tap_tool_material="HSS")
        spec_ss    = _spec(material="stainless_303", tap_tool_material="HSS")
        r_steel = check_rigid_tap(spec_steel)
        r_ss    = check_rigid_tap(spec_ss)
        assert r_ss.recommended_torque_Nm > r_steel.recommended_torque_Nm

    def test_torque_scales_with_cube_of_diameter(self):
        """T ∝ D³ — ratio of torques should equal ratio of D³ for same K."""
        spec_m6  = _spec(thread_size="M6x1.0",  material="steel_1018", tap_tool_material="HSS")
        spec_m10 = _spec(thread_size="M10x1.5", material="steel_1018", tap_tool_material="HSS")
        r_m6  = check_rigid_tap(spec_m6)
        r_m10 = check_rigid_tap(spec_m10)
        ratio_torque = r_m10.recommended_torque_Nm / r_m6.recommended_torque_Nm
        ratio_d3     = (10.0 ** 3) / (6.0 ** 3)
        assert ratio_torque == pytest.approx(ratio_d3, rel=1e-4)


# ---------------------------------------------------------------------------
# 7. Tap breakage risk
# ---------------------------------------------------------------------------

class TestTapBreakageRisk:
    def test_low_risk_shallow_normal_speed(self):
        """Shallow hole, well within rpm limit → low risk."""
        spec = _spec(
            thread_size="M10x1.5",
            material="steel_1018",
            hole_depth_mm=15.0,   # 1.5 × D — shallow
            spindle_rpm=500.0,
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        assert r.tap_breakage_risk == "low"

    def test_high_risk_deep_hole_and_high_speed(self):
        """Deep hole (> 3×D) AND rpm above limit → high risk."""
        spec = _spec(
            thread_size="M6x1.0",
            material="steel_1018",
            hole_depth_mm=30.0,    # 5× D — deep
            spindle_rpm=3000.0,    # above HSS steel limit of 1500
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        assert r.tap_breakage_risk == "high"

    def test_medium_risk_deep_hole_normal_speed(self):
        """Deep hole alone scores 1 → medium risk."""
        spec = _spec(
            thread_size="M10x1.5",
            material="steel_1018",
            hole_depth_mm=50.0,   # 5× D — definitely deep
            spindle_rpm=500.0,    # well below steel HSS limit of 1500
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        assert r.tap_breakage_risk == "medium"

    def test_high_risk_stainless_small_hss_deep(self):
        """Stainless + small HSS tap (<8 mm) + deep → high."""
        spec = _spec(
            thread_size="M5x0.8",
            material="stainless_303",
            hole_depth_mm=25.0,    # > 3×5 = 15 mm → deep flag
            spindle_rpm=400.0,     # below stainless HSS 800 rpm limit
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        # deep (+1) + stainless+small+HSS (+1) → score 2 → "high"
        assert r.tap_breakage_risk == "high"

    def test_medium_risk_high_rpm_only(self):
        """rpm above material limit but hole not deep → medium."""
        spec = _spec(
            thread_size="M10x1.5",
            material="steel_1018",
            hole_depth_mm=20.0,    # 2× D — not deep
            spindle_rpm=2000.0,    # above HSS steel 1500 limit
            tap_tool_material="HSS",
        )
        r = check_rigid_tap(spec)
        assert r.tap_breakage_risk == "medium"

    def test_carbide_aluminum_deep_still_low_risk(self):
        """Carbide in aluminum — rpm limit is high (6000) — low risk even deep."""
        spec = _spec(
            thread_size="M10x1.5",
            material="aluminum_6061",
            hole_depth_mm=50.0,    # 5× D — deep (+1)
            spindle_rpm=3000.0,    # below carbide alum 6000 → no rpm penalty
            tap_tool_material="carbide",
        )
        r = check_rigid_tap(spec)
        # Only deep hole flag fires → medium (not low)
        assert r.tap_breakage_risk == "medium"


# ---------------------------------------------------------------------------
# 8. Feed override recommendation
# ---------------------------------------------------------------------------

class TestFeedOverride:
    def test_no_override_when_sync_compliant(self):
        spec = _spec(spindle_rpm=500.0, machine_max_sync_rpm=4000)
        r = check_rigid_tap(spec)
        assert r.recommended_feed_override_pct == pytest.approx(100.0)

    def test_override_halved_when_double_max(self):
        """rpm = 8000, max = 4000 → override = 50 %."""
        spec = _spec(spindle_rpm=8000.0, machine_max_sync_rpm=4000)
        r = check_rigid_tap(spec)
        assert r.recommended_feed_override_pct == pytest.approx(50.0, rel=1e-3)

    def test_override_ratio_calculation(self):
        """Override pct = (max/rpm) × 100."""
        spec = _spec(spindle_rpm=6000.0, machine_max_sync_rpm=4000)
        r = check_rigid_tap(spec)
        expected = (4000 / 6000) * 100
        assert r.recommended_feed_override_pct == pytest.approx(expected, rel=1e-3)


# ---------------------------------------------------------------------------
# 9. Report structure — field types and ranges
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_fields_present(self):
        spec = _spec()
        r = check_rigid_tap(spec)
        assert isinstance(r.recommended_torque_Nm, float)
        assert isinstance(r.computed_feed_mm_per_min, float)
        assert isinstance(r.sync_compliant, bool)
        assert r.tap_breakage_risk in ("low", "medium", "high")
        assert isinstance(r.recommended_feed_override_pct, float)
        assert len(r.honest_caveat) > 50

    def test_torque_positive(self):
        for thread in ("M3x0.5", "M6x1.0", "M10x1.5", "M16x2.0"):
            for mat in ("steel_1018", "aluminum_6061", "stainless_303", "brass"):
                for tool in ("HSS", "cobalt", "carbide"):
                    spec = _spec(thread_size=thread, material=mat, tap_tool_material=tool)
                    r = check_rigid_tap(spec)
                    assert r.recommended_torque_Nm > 0, (
                        f"Expected positive torque for {thread}/{mat}/{tool}"
                    )

    def test_feed_positive(self):
        spec = _spec(spindle_rpm=750.0, thread_size="M8x1.25")
        r = check_rigid_tap(spec)
        assert r.computed_feed_mm_per_min > 0


# ---------------------------------------------------------------------------
# 10. Input validation — RigidTapSpec errors
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="hole_depth_mm"):
            _spec(hole_depth_mm=-5.0)

    def test_zero_depth_raises(self):
        with pytest.raises(ValueError, match="hole_depth_mm"):
            _spec(hole_depth_mm=0.0)

    def test_negative_rpm_raises(self):
        with pytest.raises(ValueError, match="spindle_rpm"):
            _spec(spindle_rpm=-100.0)

    def test_bad_material_raises(self):
        with pytest.raises(ValueError, match="material"):
            _spec(material="unobtainium")

    def test_bad_tool_material_raises(self):
        with pytest.raises(ValueError, match="tap_tool_material"):
            _spec(tap_tool_material="wood")

    def test_bad_thread_size_raises(self):
        with pytest.raises(ValueError, match="Unrecognised thread_size"):
            _spec(thread_size="X99q")


# ---------------------------------------------------------------------------
# 11. LLM tool spec
# ---------------------------------------------------------------------------

class TestLLMToolSpec:
    def test_spec_name(self):
        assert cam_check_rigid_tap_spec.name == "cam_check_rigid_tap"

    def test_spec_description_mentions_references(self):
        desc = cam_check_rigid_tap_spec.description
        assert "MH 31e §1934" in desc
        assert "Sandvik" in desc

    def test_spec_required_fields(self):
        required = cam_check_rigid_tap_spec.input_schema["required"]
        for f in [
            "thread_size", "material", "hole_depth_mm",
            "spindle_rpm", "machine_max_sync_rpm", "tap_tool_material",
        ]:
            assert f in required


# ---------------------------------------------------------------------------
# 12. LLM tool runner — async roundtrip
# ---------------------------------------------------------------------------

class TestLLMToolRunner:
    def _call(self, payload: dict) -> dict:
        raw = asyncio.get_event_loop().run_until_complete(
            run_cam_check_rigid_tap(None, json.dumps(payload).encode())
        )
        return json.loads(raw)

    def test_valid_m6_steel_hss(self):
        result = self._call({
            "thread_size": "M6x1.0",
            "material": "steel_1018",
            "hole_depth_mm": 15.0,
            "spindle_rpm": 500,
            "machine_max_sync_rpm": 4000,
            "tap_tool_material": "HSS",
        })
        assert result["sync_compliant"] is True
        assert result["computed_feed_mm_per_min"] == pytest.approx(500.0)
        assert "recommended_torque_Nm" in result
        assert "tap_breakage_risk" in result

    def test_valid_m10_stainless_not_compliant(self):
        result = self._call({
            "thread_size": "M10x1.5",
            "material": "stainless_303",
            "hole_depth_mm": 20.0,
            "spindle_rpm": 6000,
            "machine_max_sync_rpm": 4000,
            "tap_tool_material": "HSS",
        })
        assert result["sync_compliant"] is False
        assert result["recommended_feed_override_pct"] < 100.0

    def test_missing_field_returns_error(self):
        result = self._call({
            "thread_size": "M6x1.0",
            "material": "steel_1018",
            # hole_depth_mm missing
            "spindle_rpm": 500,
            "machine_max_sync_rpm": 4000,
            "tap_tool_material": "HSS",
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_bad_material_returns_error(self):
        result = self._call({
            "thread_size": "M6x1.0",
            "material": "titanium_super",
            "hole_depth_mm": 10.0,
            "spindle_rpm": 500,
            "machine_max_sync_rpm": 4000,
            "tap_tool_material": "HSS",
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_json_returns_error(self):
        raw = asyncio.get_event_loop().run_until_complete(
            run_cam_check_rigid_tap(None, b"{bad json{{")
        )
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_inch_thread_quarter_20(self):
        result = self._call({
            "thread_size": "1/4-20",
            "material": "aluminum_6061",
            "hole_depth_mm": 12.0,
            "spindle_rpm": 1500,
            "machine_max_sync_rpm": 6000,
            "tap_tool_material": "carbide",
        })
        assert result["sync_compliant"] is True
        expected_feed = (25.4 / 20) * 1500
        assert result["computed_feed_mm_per_min"] == pytest.approx(expected_feed, rel=1e-3)

    def test_honest_caveat_present(self):
        result = self._call({
            "thread_size": "M8x1.25",
            "material": "brass",
            "hole_depth_mm": 10.0,
            "spindle_rpm": 800,
            "machine_max_sync_rpm": 3000,
            "tap_tool_material": "cobalt",
        })
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 50


# ---------------------------------------------------------------------------
# 13. K-table completeness
# ---------------------------------------------------------------------------

class TestKTableCompleteness:
    def test_all_material_tool_combos_have_k(self):
        materials = ["steel_1018", "aluminum_6061", "stainless_303", "brass"]
        tools = ["HSS", "cobalt", "carbide"]
        for mat in materials:
            for tool in tools:
                key = (mat, tool)
                assert key in _K_TABLE, f"Missing K for {key}"
                assert _K_TABLE[key] > 0

    def test_all_material_tool_combos_have_rpm_limit(self):
        materials = ["steel_1018", "aluminum_6061", "stainless_303", "brass"]
        tools = ["HSS", "cobalt", "carbide"]
        for mat in materials:
            for tool in tools:
                key = (mat, tool)
                assert key in _RPM_LIMIT, f"Missing RPM limit for {key}"
                assert _RPM_LIMIT[key] > 0
