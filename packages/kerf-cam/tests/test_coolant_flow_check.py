"""
Tests for kerf_cam.coolant_flow_check — coolant flow rate and pressure checker.

References
----------
* Sandvik CoroPlus Coolant Application Guide §3 (2024)
* Machinery's Handbook 31e §1140 (Coolant application)
"""

from __future__ import annotations

import pytest

from kerf_cam.coolant_flow_check import (
    CoolantFlowReport,
    MachiningOpForCoolant,
    check_coolant_flow,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_spec(**kwargs) -> MachiningOpForCoolant:
    """Build a MachiningOpForCoolant with sensible defaults, overridden by kwargs."""
    defaults = dict(
        mrr_cm3_per_min=10.0,
        tool_diameter_mm=12.0,
        axial_depth_mm=5.0,
        material="steel",
        coolant_type="flood",
        available_flow_L_per_min=15.0,
        available_pressure_bar=10.0,
    )
    defaults.update(kwargs)
    return MachiningOpForCoolant(**defaults)


# ---------------------------------------------------------------------------
# T1 — Steel MRR=20 flood, 15 L/min available: required=10 L/min → adequate
# ---------------------------------------------------------------------------

class TestSteelFloodAdequate:
    def test_steel_20mrr_required_flow(self):
        """Steel MRR=20 cm³/min: required = 0.5×20 = 10 L/min (Sandvik §3)."""
        spec = _make_spec(
            mrr_cm3_per_min=20.0,
            material="steel",
            coolant_type="flood",
            available_flow_L_per_min=15.0,
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_flow_L_per_min == pytest.approx(10.0, abs=1e-4)

    def test_steel_20mrr_flow_adequate(self):
        """15 L/min available >= 10 required → flow_adequate = True."""
        spec = _make_spec(
            mrr_cm3_per_min=20.0,
            material="steel",
            coolant_type="flood",
            available_flow_L_per_min=15.0,
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.flow_adequate is True

    def test_steel_20mrr_flood_pressure_adequate(self):
        """Flood requires ≥2 bar; 5 bar available → pressure_adequate = True."""
        spec = _make_spec(
            mrr_cm3_per_min=20.0,
            material="steel",
            coolant_type="flood",
            available_flow_L_per_min=15.0,
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is True

    def test_steel_flow_inadequate_below_required(self):
        """Available flow below required → flow_adequate = False."""
        spec = _make_spec(
            mrr_cm3_per_min=20.0,
            material="steel",
            coolant_type="flood",
            available_flow_L_per_min=8.0,   # less than 10 required
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.flow_adequate is False


# ---------------------------------------------------------------------------
# T2 — Aluminum MRR=30: required = 9 L/min
# ---------------------------------------------------------------------------

class TestAluminumFlow:
    def test_aluminum_30mrr_required_flow(self):
        """Aluminum MRR=30 cm³/min: required = 0.3×30 = 9 L/min (Sandvik §3)."""
        spec = _make_spec(
            mrr_cm3_per_min=30.0,
            material="aluminum",
            coolant_type="flood",
            available_flow_L_per_min=12.0,
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_flow_L_per_min == pytest.approx(9.0, abs=1e-4)

    def test_aluminum_30mrr_flow_adequate(self):
        """12 L/min available >= 9 required → flow_adequate = True."""
        spec = _make_spec(
            mrr_cm3_per_min=30.0,
            material="aluminum",
            coolant_type="flood",
            available_flow_L_per_min=12.0,
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.flow_adequate is True

    def test_aluminum_lower_factor_than_steel(self):
        """Aluminum flow factor (0.30) is lower than steel (0.50)."""
        spec_al = _make_spec(material="aluminum", mrr_cm3_per_min=10.0)
        spec_st = _make_spec(material="steel", mrr_cm3_per_min=10.0)
        report_al = check_coolant_flow(spec_al)
        report_st = check_coolant_flow(spec_st)
        assert report_al.required_flow_L_per_min < report_st.required_flow_L_per_min

    def test_aluminum_recommended_coolant(self):
        """Aluminum recommended coolant type is flood (Sandvik §3)."""
        spec = _make_spec(material="aluminum")
        report = check_coolant_flow(spec)
        assert report.recommended_coolant_type == "flood"


# ---------------------------------------------------------------------------
# T3 — Through-tool 12mm dia at 10 bar → pressure inadequate (need 20)
# ---------------------------------------------------------------------------

class TestThroughToolPressure:
    def test_through_tool_12mm_10bar_pressure_inadequate(self):
        """Through-tool d=12mm (>8mm) requires ≥20 bar; 10 bar → inadequate."""
        spec = _make_spec(
            tool_diameter_mm=12.0,
            coolant_type="through_tool",
            available_pressure_bar=10.0,
        )
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is False
        assert report.required_pressure_bar == pytest.approx(20.0, abs=1e-4)

    def test_through_tool_12mm_25bar_pressure_adequate(self):
        """Through-tool d=12mm at 25 bar → pressure_adequate = True."""
        spec = _make_spec(
            tool_diameter_mm=12.0,
            coolant_type="through_tool",
            available_pressure_bar=25.0,
        )
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is True

    def test_through_tool_small_tool_lower_pressure(self):
        """Through-tool d=6mm (≤8mm) requires only ≥10 bar."""
        spec = _make_spec(
            tool_diameter_mm=6.0,
            coolant_type="through_tool",
            available_pressure_bar=12.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_pressure_bar == pytest.approx(10.0, abs=1e-4)
        assert report.pressure_adequate is True

    def test_through_tool_exactly_8mm_boundary(self):
        """Through-tool d=8mm (= threshold, not >8mm) → uses small-tool 10 bar."""
        spec = _make_spec(
            tool_diameter_mm=8.0,
            coolant_type="through_tool",
            available_pressure_bar=12.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_pressure_bar == pytest.approx(10.0, abs=1e-4)
        assert report.pressure_adequate is True


# ---------------------------------------------------------------------------
# T4 — Titanium → recommend high-pressure through-tool
# ---------------------------------------------------------------------------

class TestTitanium:
    def test_titanium_requires_70bar(self):
        """Titanium: required_pressure = 70 bar (Sandvik CoroPlus §3 mandate)."""
        spec = _make_spec(
            material="titanium",
            coolant_type="through_tool",
            available_pressure_bar=50.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_pressure_bar == pytest.approx(70.0, abs=1e-4)

    def test_titanium_pressure_inadequate_at_50bar(self):
        """50 bar < 70 required → pressure_adequate = False for titanium."""
        spec = _make_spec(
            material="titanium",
            coolant_type="through_tool",
            available_pressure_bar=50.0,
        )
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is False

    def test_titanium_pressure_adequate_at_70bar(self):
        """70 bar >= 70 required → pressure_adequate = True."""
        spec = _make_spec(
            material="titanium",
            coolant_type="through_tool",
            available_pressure_bar=70.0,
        )
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is True

    def test_titanium_recommended_coolant_through_tool(self):
        """Titanium recommended coolant type is through_tool (Sandvik §3)."""
        spec = _make_spec(material="titanium")
        report = check_coolant_flow(spec)
        assert report.recommended_coolant_type == "through_tool"

    def test_titanium_70bar_even_for_flood(self):
        """Titanium 70 bar mandate applies even when coolant_type=flood."""
        spec = _make_spec(
            material="titanium",
            coolant_type="flood",
            available_pressure_bar=30.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_pressure_bar == pytest.approx(70.0, abs=1e-4)
        assert report.pressure_adequate is False


# ---------------------------------------------------------------------------
# T5 — Stainless steel
# ---------------------------------------------------------------------------

class TestStainless:
    def test_stainless_flow_factor(self):
        """Stainless MRR=10: required = 0.6×10 = 6 L/min."""
        spec = _make_spec(
            mrr_cm3_per_min=10.0,
            material="stainless",
            coolant_type="flood",
            available_flow_L_per_min=8.0,
            available_pressure_bar=5.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_flow_L_per_min == pytest.approx(6.0, abs=1e-4)

    def test_stainless_higher_factor_than_steel(self):
        """Stainless factor (0.60) > steel factor (0.50)."""
        spec_ss = _make_spec(material="stainless", mrr_cm3_per_min=10.0)
        spec_st = _make_spec(material="steel", mrr_cm3_per_min=10.0)
        assert (
            check_coolant_flow(spec_ss).required_flow_L_per_min
            > check_coolant_flow(spec_st).required_flow_L_per_min
        )

    def test_stainless_recommended_through_tool(self):
        """Stainless recommended coolant type is through_tool (Sandvik §3)."""
        spec = _make_spec(material="stainless")
        report = check_coolant_flow(spec)
        assert report.recommended_coolant_type == "through_tool"


# ---------------------------------------------------------------------------
# T6 — Composite
# ---------------------------------------------------------------------------

class TestComposite:
    def test_composite_flow_factor(self):
        """Composite MRR=10: required = 0.2×10 = 2 L/min."""
        spec = _make_spec(
            mrr_cm3_per_min=10.0,
            material="composite",
            coolant_type="MQL",
            available_flow_L_per_min=3.0,
            available_pressure_bar=6.0,
        )
        report = check_coolant_flow(spec)
        assert report.required_flow_L_per_min == pytest.approx(2.0, abs=1e-4)

    def test_composite_lowest_flow_factor(self):
        """Composite factor (0.20) is the lowest of all materials."""
        reports = [
            check_coolant_flow(_make_spec(material=m, mrr_cm3_per_min=10.0))
            for m in ["steel", "stainless", "aluminum", "titanium", "composite"]
        ]
        composite_flow = check_coolant_flow(
            _make_spec(material="composite", mrr_cm3_per_min=10.0)
        ).required_flow_L_per_min
        for r in reports:
            assert composite_flow <= r.required_flow_L_per_min

    def test_composite_recommended_mql(self):
        """Composite recommended coolant type is MQL (Sandvik §3)."""
        spec = _make_spec(material="composite")
        report = check_coolant_flow(spec)
        assert report.recommended_coolant_type == "MQL"


# ---------------------------------------------------------------------------
# T7 — Mist and MQL pressure minimums
# ---------------------------------------------------------------------------

class TestMistMQL:
    def test_mist_minimum_pressure_4bar(self):
        """Mist requires ≥4 bar (Sandvik CoroPlus §3 atomising pressure)."""
        spec = _make_spec(coolant_type="mist", available_pressure_bar=3.0)
        report = check_coolant_flow(spec)
        assert report.required_pressure_bar == pytest.approx(4.0, abs=1e-4)
        assert report.pressure_adequate is False

    def test_mql_minimum_pressure_5bar(self):
        """MQL requires ≥5 bar (atomising air pressure)."""
        spec = _make_spec(coolant_type="MQL", available_pressure_bar=4.5)
        report = check_coolant_flow(spec)
        assert report.required_pressure_bar == pytest.approx(5.0, abs=1e-4)
        assert report.pressure_adequate is False

    def test_mql_adequate_at_5bar(self):
        """MQL at exactly 5 bar → pressure_adequate = True."""
        spec = _make_spec(coolant_type="MQL", available_pressure_bar=5.0)
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is True


# ---------------------------------------------------------------------------
# T8 — Return type and honest caveat
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_coolant_flow_report(self):
        """check_coolant_flow always returns a CoolantFlowReport instance."""
        report = check_coolant_flow(_make_spec())
        assert isinstance(report, CoolantFlowReport)

    def test_honest_caveat_non_empty(self):
        """honest_caveat must be a non-empty string."""
        report = check_coolant_flow(_make_spec())
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 0

    def test_honest_caveat_mentions_chemistry(self):
        """Caveat must mention coolant chemistry being out of scope."""
        caveat = check_coolant_flow(_make_spec()).honest_caveat.lower()
        assert "chemistry" in caveat or "concentration" in caveat

    def test_honest_caveat_mentions_chip_evacuation(self):
        """Caveat must mention chip-evacuation not being modelled."""
        caveat = check_coolant_flow(_make_spec()).honest_caveat.lower()
        assert "chip" in caveat


# ---------------------------------------------------------------------------
# T9 — Validation / error handling
# ---------------------------------------------------------------------------

class TestValidation:
    def test_zero_mrr_raises(self):
        with pytest.raises(ValueError, match="mrr_cm3_per_min"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=0.0, tool_diameter_mm=12.0, axial_depth_mm=5.0,
                material="steel", coolant_type="flood",
                available_flow_L_per_min=10.0, available_pressure_bar=5.0,
            )

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="tool_diameter_mm"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=10.0, tool_diameter_mm=0.0, axial_depth_mm=5.0,
                material="steel", coolant_type="flood",
                available_flow_L_per_min=10.0, available_pressure_bar=5.0,
            )

    def test_zero_axial_depth_raises(self):
        with pytest.raises(ValueError, match="axial_depth_mm"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=10.0, tool_diameter_mm=12.0, axial_depth_mm=0.0,
                material="steel", coolant_type="flood",
                available_flow_L_per_min=10.0, available_pressure_bar=5.0,
            )

    def test_invalid_material_raises(self):
        with pytest.raises(ValueError, match="material"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=10.0, tool_diameter_mm=12.0, axial_depth_mm=5.0,
                material="unobtainium", coolant_type="flood",
                available_flow_L_per_min=10.0, available_pressure_bar=5.0,
            )

    def test_invalid_coolant_type_raises(self):
        with pytest.raises(ValueError, match="coolant_type"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=10.0, tool_diameter_mm=12.0, axial_depth_mm=5.0,
                material="steel", coolant_type="submerged",
                available_flow_L_per_min=10.0, available_pressure_bar=5.0,
            )

    def test_negative_available_flow_raises(self):
        with pytest.raises(ValueError, match="available_flow_L_per_min"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=10.0, tool_diameter_mm=12.0, axial_depth_mm=5.0,
                material="steel", coolant_type="flood",
                available_flow_L_per_min=-1.0, available_pressure_bar=5.0,
            )

    def test_negative_available_pressure_raises(self):
        with pytest.raises(ValueError, match="available_pressure_bar"):
            MachiningOpForCoolant(
                mrr_cm3_per_min=10.0, tool_diameter_mm=12.0, axial_depth_mm=5.0,
                material="steel", coolant_type="flood",
                available_flow_L_per_min=10.0, available_pressure_bar=-1.0,
            )


# ---------------------------------------------------------------------------
# T10 — Zero available flow/pressure → always inadequate
# ---------------------------------------------------------------------------

class TestZeroAvailable:
    def test_zero_flow_always_inadequate(self):
        """Zero available flow is always inadequate for any positive MRR."""
        spec = _make_spec(available_flow_L_per_min=0.0)
        report = check_coolant_flow(spec)
        assert report.flow_adequate is False

    def test_zero_pressure_always_inadequate(self):
        """Zero available pressure is always inadequate."""
        spec = _make_spec(available_pressure_bar=0.0)
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is False


# ---------------------------------------------------------------------------
# T11 — Boundary: available exactly equals required
# ---------------------------------------------------------------------------

class TestExactBoundary:
    def test_exact_required_flow_is_adequate(self):
        """Available exactly equals required → flow_adequate = True."""
        spec = _make_spec(
            mrr_cm3_per_min=20.0,
            material="steel",
            available_flow_L_per_min=10.0,   # exact = 0.5 × 20
        )
        report = check_coolant_flow(spec)
        assert report.flow_adequate is True

    def test_exact_required_pressure_is_adequate(self):
        """Available pressure exactly equals required → pressure_adequate = True."""
        spec = _make_spec(
            coolant_type="through_tool",
            tool_diameter_mm=12.0,
            available_pressure_bar=20.0,   # exact minimum
        )
        report = check_coolant_flow(spec)
        assert report.pressure_adequate is True
