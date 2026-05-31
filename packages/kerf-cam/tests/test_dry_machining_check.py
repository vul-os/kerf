"""
Tests for kerf_cam.dry_machining_check — dry-machining feasibility checker.

References
----------
* Sandvik Coromant Dry and Near-Dry Machining Application Guide (2024)
* ISO 8688-1:1989 — Tool life testing in milling
* Klocke F., Eisenblätter G. "Dry cutting" CIRP Ann. 46(2) 1997
* Biermann D. et al. "Dry and Near-Dry Machining" Springer 2020 §4
"""

from __future__ import annotations

import pytest

from kerf_cam.dry_machining_check import (
    DryMachiningReport,
    DryMachiningSpec,
    check_dry_machining,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**kwargs) -> DryMachiningSpec:
    """Build a DryMachiningSpec with sensible defaults, overridden by kwargs."""
    defaults = dict(
        workpiece_material="cast-iron-grey",
        tool_coating="TiAlN",
        vc_m_per_min=150.0,
        fz_mm_per_tooth=0.10,
        ae_mm=5.0,
        ap_mm=3.0,
        tool_diameter_mm=16.0,
        operation="milling-finishing",
    )
    defaults.update(kwargs)
    return DryMachiningSpec(**defaults)


# ---------------------------------------------------------------------------
# T1 — Grey cast iron + TiAlN milling: feasible, factor ≈ 0.95
# ---------------------------------------------------------------------------

class TestGreyCastIronTiAlN:
    """Sandvik Coromant §5: grey cast iron is the benchmark dry-machining material."""

    def test_feasible_is_true(self):
        """Grey cast iron + TiAlN milling-finishing → feasible = True."""
        report = check_dry_machining(
            _spec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                operation="milling-finishing",
            )
        )
        assert report.feasible is True

    def test_factor_approximately_0_95(self):
        """Tool-life reduction factor for grey cast iron ≈ 0.95 (range 0.90-1.00)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                operation="milling-finishing",
            )
        )
        assert report.tool_life_reduction_factor == pytest.approx(0.95, abs=0.05)

    def test_factor_in_range_0_90_to_1_00(self):
        """Grey cast iron factor must be in [0.90, 1.00] per Sandvik §5."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="TiAlN")
        )
        assert 0.90 <= report.tool_life_reduction_factor <= 1.00

    def test_uncoated_also_feasible(self):
        """Uncoated carbide is acceptable for grey cast iron dry machining."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="uncoated")
        )
        assert report.feasible is True

    def test_recommendation_mentions_feasible(self):
        """Recommendation text must mention feasibility for grey cast iron."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="TiAlN")
        )
        assert "feasible" in report.recommendation.lower() or \
               "FEASIBLE" in report.recommendation

    def test_returns_dry_machining_report_type(self):
        """check_dry_machining must return DryMachiningReport."""
        report = check_dry_machining(_spec())
        assert isinstance(report, DryMachiningReport)


# ---------------------------------------------------------------------------
# T2 — Aluminum wrought + uncoated: NOT feasible (chip welding / BUE)
# ---------------------------------------------------------------------------

class TestAluminumWroughtUncoated:
    """Sandvik Coromant §3: Al wrought → BUE / gumming; flood or MQL required."""

    def test_not_feasible(self):
        """Aluminum wrought + uncoated → feasible = False (chip welding risk)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="aluminum-wrought",
                tool_coating="uncoated",
            )
        )
        assert report.feasible is False

    def test_not_feasible_with_tiain_either(self):
        """TiAlN accelerates BUE on Al — not feasible dry."""
        report = check_dry_machining(
            _spec(
                workpiece_material="aluminum-wrought",
                tool_coating="TiAlN",
            )
        )
        assert report.feasible is False

    def test_warning_mentions_bue_or_chip_welding(self):
        """Warnings must mention built-up edge or chip-welding for Al."""
        report = check_dry_machining(
            _spec(workpiece_material="aluminum-wrought", tool_coating="uncoated")
        )
        combined = " ".join(report.warnings).lower()
        assert "built-up edge" in combined or "bue" in combined or \
               "chip-welding" in combined or "welding" in combined

    def test_warning_mentions_flood_or_mql(self):
        """Recommendations for Al must suggest flood or MQL."""
        report = check_dry_machining(
            _spec(workpiece_material="aluminum-wrought", tool_coating="uncoated")
        )
        combined = (report.recommendation + " " + " ".join(report.warnings)).lower()
        assert "flood" in combined or "mql" in combined

    def test_min_coating_required_is_diamond_cvd(self):
        """min_coating_required for aluminum should be diamond-CVD."""
        report = check_dry_machining(
            _spec(workpiece_material="aluminum-wrought", tool_coating="uncoated")
        )
        assert report.min_coating_required == "diamond-CVD"

    def test_factor_below_0_65(self):
        """Al wrought tool-life reduction factor must be well below 0.65."""
        report = check_dry_machining(
            _spec(workpiece_material="aluminum-wrought", tool_coating="uncoated")
        )
        assert report.tool_life_reduction_factor < 0.65


# ---------------------------------------------------------------------------
# T3 — 316L stainless + uncoated: NOT feasible
# ---------------------------------------------------------------------------

class TestStainlessUncoated:
    """Sandvik §6 + ISO 8688-1: austenitic stainless needs AlCrN/TiAlN for dry."""

    def test_not_feasible_uncoated(self):
        """Stainless + uncoated → NOT feasible (rapid BUE + crater wear)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="uncoated",
            )
        )
        assert report.feasible is False

    def test_not_feasible_tin(self):
        """Stainless + TiN → NOT feasible (insufficient hot-hardness)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="TiN",
            )
        )
        assert report.feasible is False

    def test_coating_warning_present(self):
        """Coating inadequacy warning must be issued for uncoated on stainless."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="uncoated",
            )
        )
        assert len(report.warnings) > 0
        combined = " ".join(report.warnings).lower()
        assert "coating" in combined or "not adequate" in combined


# ---------------------------------------------------------------------------
# T4 — 316L stainless + AlCrN, within derated vc: feasible
# ---------------------------------------------------------------------------

class TestStainlessAlCrNDerated:
    """Sandvik §6: stainless + AlCrN + 30-50% vc derate → conditional feasible."""

    def test_feasible_with_alcrn(self):
        """Stainless + AlCrN at conservative vc → feasible = True."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                vc_m_per_min=80.0,  # conservative dry speed for stainless
                operation="milling-finishing",
            )
        )
        assert report.feasible is True

    def test_feasible_with_tialn_derated(self):
        """Stainless + TiAlN at derated vc → feasible = True."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="TiAlN",
                vc_m_per_min=70.0,
                operation="milling-finishing",
            )
        )
        assert report.feasible is True

    def test_min_coating_required_is_tialn(self):
        """min_coating_required for stainless must be TiAlN (Sandvik §6)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
            )
        )
        assert report.min_coating_required == "TiAlN"

    def test_factor_in_expected_range(self):
        """Stainless + AlCrN factor should be in 0.50-0.65 range."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                vc_m_per_min=80.0,
            )
        )
        assert 0.40 <= report.tool_life_reduction_factor <= 0.75

    def test_recommendation_mentions_vc_derate(self):
        """Recommendation for stainless must mention vc reduction requirement."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
            )
        )
        text = report.recommendation.lower()
        assert "vc" in text or "speed" in text or "derate" in text or "reduction" in text


# ---------------------------------------------------------------------------
# T5 — Ti6Al4V dry: warn — needs MQL
# ---------------------------------------------------------------------------

class TestTi6Al4VDry:
    """Biermann 2020 §4: Ti6Al4V dry → challenging; MQL minimum."""

    def test_not_fully_feasible_dry(self):
        """Ti6Al4V fully dry → feasible = False (no adequate dry coating)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="titanium-Ti6Al4V",
                tool_coating="uncoated",
                vc_m_per_min=50.0,
            )
        )
        assert report.feasible is False

    def test_mql_warning_present(self):
        """MQL warning must be present for any Ti6Al4V dry scenario."""
        report = check_dry_machining(
            _spec(
                workpiece_material="titanium-Ti6Al4V",
                tool_coating="TiAlN",
                vc_m_per_min=45.0,
            )
        )
        combined = " ".join(report.warnings).lower()
        assert "mql" in combined or "minimum-quantity" in combined

    def test_combustion_warning_above_60_m_per_min(self):
        """Combustion risk warning must fire when vc > 60 m/min on Ti6Al4V."""
        report = check_dry_machining(
            _spec(
                workpiece_material="titanium-Ti6Al4V",
                tool_coating="AlCrN",
                vc_m_per_min=80.0,  # above 60 m/min threshold
            )
        )
        combined = " ".join(report.warnings).lower()
        assert "combustion" in combined or "critical" in combined

    def test_no_combustion_warning_below_60_m_per_min(self):
        """Below 60 m/min: no combustion warning, but MQL warning still present."""
        report = check_dry_machining(
            _spec(
                workpiece_material="titanium-Ti6Al4V",
                tool_coating="AlCrN",
                vc_m_per_min=50.0,  # below 60 m/min
            )
        )
        combined = " ".join(report.warnings).lower()
        assert "combustion" not in combined
        assert "mql" in combined or "minimum-quantity" in combined

    def test_factor_well_below_flood(self):
        """Ti6Al4V factor must be below 0.55 (extreme thermal penalty)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="titanium-Ti6Al4V",
                tool_coating="AlCrN",
                vc_m_per_min=50.0,
            )
        )
        assert report.tool_life_reduction_factor <= 0.55

    def test_challenging_coating_tialn_sets_feasible_true(self):
        """Ti6Al4V + TiAlN coating → feasible = True (challenging but possible with MQL)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="titanium-Ti6Al4V",
                tool_coating="TiAlN",
                vc_m_per_min=45.0,
            )
        )
        assert report.feasible is True


# ---------------------------------------------------------------------------
# T6 — Cast iron + uncoated: still feasible (graphite lubrication)
# ---------------------------------------------------------------------------

class TestCastIronUncoated:
    def test_uncoated_carbide_feasible(self):
        """Uncoated carbide is acceptable for grey cast iron (Sandvik §5)."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="uncoated")
        )
        assert report.feasible is True

    def test_diamond_cvd_not_feasible_on_cast_iron(self):
        """Diamond-CVD NOT recommended for cast iron (graphite adhesion)."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="diamond-CVD")
        )
        assert report.feasible is False


# ---------------------------------------------------------------------------
# T7 — Inconel 718: dry NOT feasible regardless of coating
# ---------------------------------------------------------------------------

class TestInconel718:
    def test_not_feasible_any_coating(self):
        """Inconel 718: dry NOT feasible for all coatings (flood mandatory)."""
        for coating in ["uncoated", "TiN", "TiAlN", "AlCrN", "diamond-CVD"]:
            report = check_dry_machining(
                _spec(workpiece_material="nickel-inconel-718", tool_coating=coating)
            )
            assert report.feasible is False, f"Expected not feasible for coating={coating}"

    def test_warning_mentions_flood(self):
        """Inconel 718 warnings must recommend flood coolant."""
        report = check_dry_machining(
            _spec(workpiece_material="nickel-inconel-718", tool_coating="AlCrN")
        )
        combined = " ".join(report.warnings).lower()
        assert "flood" in combined

    def test_factor_very_low(self):
        """Inconel 718 factor must be ≤ 0.45 (extreme penalty)."""
        report = check_dry_machining(
            _spec(workpiece_material="nickel-inconel-718", tool_coating="AlCrN")
        )
        assert report.tool_life_reduction_factor <= 0.45


# ---------------------------------------------------------------------------
# T8 — Low-carbon steel + TiAlN: conditional feasible
# ---------------------------------------------------------------------------

class TestSteelLowCarbonTiAlN:
    def test_feasible_true(self):
        """Low-carbon steel + TiAlN → feasible = True (conditional)."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-low-carbon",
                tool_coating="TiAlN",
                vc_m_per_min=120.0,
            )
        )
        assert report.feasible is True

    def test_factor_in_conditional_range(self):
        """Low-carbon steel factor should be in 0.65-0.90 range."""
        report = check_dry_machining(
            _spec(workpiece_material="steel-low-carbon", tool_coating="TiAlN")
        )
        assert 0.60 <= report.tool_life_reduction_factor <= 0.90

    def test_uncoated_not_feasible(self):
        """Uncoated carbide on low-carbon steel → NOT feasible."""
        report = check_dry_machining(
            _spec(workpiece_material="steel-low-carbon", tool_coating="uncoated")
        )
        assert report.feasible is False


# ---------------------------------------------------------------------------
# T9 — Vc over-speed warning fires for stainless
# ---------------------------------------------------------------------------

class TestVcOverspeedWarning:
    def test_vc_overspeed_warning_fires(self):
        """Vc significantly above max_dry_vc must trigger a warning."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                vc_m_per_min=300.0,  # way too fast for dry stainless
            )
        )
        combined = " ".join(report.warnings).lower()
        assert "exceed" in combined or "exceeds" in combined or "vc" in combined

    def test_vc_overspeed_reduces_factor(self):
        """Exceeding max_dry_vc reduces tool_life_reduction_factor."""
        report_ok = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                vc_m_per_min=80.0,  # within range
            )
        )
        report_fast = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                vc_m_per_min=300.0,  # over range
            )
        )
        assert report_fast.tool_life_reduction_factor < report_ok.tool_life_reduction_factor


# ---------------------------------------------------------------------------
# T10 — Aggressive ae/D ratio warning
# ---------------------------------------------------------------------------

class TestAggressiveEngagement:
    def test_large_ae_warning_on_stainless(self):
        """ae/D > 0.50 on stainless should trigger an engagement warning."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                ae_mm=12.0,       # ae/D = 0.75 (12/16)
                tool_diameter_mm=16.0,
            )
        )
        combined = " ".join(report.warnings).lower()
        assert "engagement" in combined or "ae" in combined or "radial" in combined


# ---------------------------------------------------------------------------
# T11 — Roughing penalty on challenging materials
# ---------------------------------------------------------------------------

class TestRoughingPenalty:
    def test_roughing_lowers_factor_vs_finishing(self):
        """Milling roughing on stainless should yield lower factor than finishing."""
        report_rough = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                operation="milling-roughing",
            )
        )
        report_finish = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                operation="milling-finishing",
            )
        )
        assert report_rough.tool_life_reduction_factor <= report_finish.tool_life_reduction_factor

    def test_roughing_warning_on_challenging(self):
        """Milling roughing on stainless should include a roughing-specific warning."""
        report = check_dry_machining(
            _spec(
                workpiece_material="steel-stainless-austenitic",
                tool_coating="AlCrN",
                operation="milling-roughing",
            )
        )
        combined = " ".join(report.warnings).lower()
        assert "rough" in combined or "thermal cycling" in combined


# ---------------------------------------------------------------------------
# T12 — Honest caveat and return type checks
# ---------------------------------------------------------------------------

class TestReturnTypeAndCaveat:
    def test_returns_dry_machining_report(self):
        """check_dry_machining always returns a DryMachiningReport instance."""
        report = check_dry_machining(_spec())
        assert isinstance(report, DryMachiningReport)

    def test_honest_caveat_non_empty(self):
        """honest_caveat must be a non-empty string."""
        report = check_dry_machining(_spec())
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 50

    def test_honest_caveat_mentions_heuristic(self):
        """Caveat must mention 'heuristic' to warn about rule-based nature."""
        caveat = check_dry_machining(_spec()).honest_caveat.lower()
        assert "heuristic" in caveat or "catalog" in caveat

    def test_warnings_is_list(self):
        """warnings must be a list (possibly empty)."""
        report = check_dry_machining(_spec())
        assert isinstance(report.warnings, list)

    def test_tool_life_factor_between_0_and_1_05(self):
        """tool_life_reduction_factor must be in plausible range [0.10, 1.05]."""
        for mat in [
            "cast-iron-grey", "steel-low-carbon", "aluminum-wrought",
            "titanium-Ti6Al4V", "nickel-inconel-718",
        ]:
            for coating in ["uncoated", "TiAlN", "AlCrN"]:
                report = check_dry_machining(
                    _spec(workpiece_material=mat, tool_coating=coating)
                )
                assert 0.10 <= report.tool_life_reduction_factor <= 1.05, (
                    f"factor out of range for {mat}+{coating}: "
                    f"{report.tool_life_reduction_factor}"
                )


# ---------------------------------------------------------------------------
# T13 — Validation errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_material_raises(self):
        with pytest.raises(ValueError, match="workpiece_material"):
            DryMachiningSpec(
                workpiece_material="unobtainium",
                tool_coating="TiAlN",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.10,
                ae_mm=5.0,
                ap_mm=3.0,
                tool_diameter_mm=16.0,
                operation="milling-finishing",
            )

    def test_invalid_coating_raises(self):
        with pytest.raises(ValueError, match="tool_coating"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="ChromiumNitride",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.10,
                ae_mm=5.0,
                ap_mm=3.0,
                tool_diameter_mm=16.0,
                operation="milling-finishing",
            )

    def test_zero_vc_raises(self):
        with pytest.raises(ValueError, match="vc_m_per_min"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=0.0,
                fz_mm_per_tooth=0.10,
                ae_mm=5.0,
                ap_mm=3.0,
                tool_diameter_mm=16.0,
                operation="milling-finishing",
            )

    def test_zero_fz_raises(self):
        with pytest.raises(ValueError, match="fz_mm_per_tooth"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.0,
                ae_mm=5.0,
                ap_mm=3.0,
                tool_diameter_mm=16.0,
                operation="milling-finishing",
            )

    def test_zero_ae_raises(self):
        with pytest.raises(ValueError, match="ae_mm"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.10,
                ae_mm=0.0,
                ap_mm=3.0,
                tool_diameter_mm=16.0,
                operation="milling-finishing",
            )

    def test_zero_ap_raises(self):
        with pytest.raises(ValueError, match="ap_mm"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.10,
                ae_mm=5.0,
                ap_mm=0.0,
                tool_diameter_mm=16.0,
                operation="milling-finishing",
            )

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="tool_diameter_mm"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.10,
                ae_mm=5.0,
                ap_mm=3.0,
                tool_diameter_mm=0.0,
                operation="milling-finishing",
            )

    def test_invalid_operation_raises(self):
        with pytest.raises(ValueError, match="operation"):
            DryMachiningSpec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=100.0,
                fz_mm_per_tooth=0.10,
                ae_mm=5.0,
                ap_mm=3.0,
                tool_diameter_mm=16.0,
                operation="laser-cutting",
            )


# ---------------------------------------------------------------------------
# T14 — TiN marginal coating warning
# ---------------------------------------------------------------------------

class TestTiNMarginalWarning:
    def test_tin_warning_on_cast_iron(self):
        """TiN is technically OK on cast iron but suboptimal — warning must fire."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="TiN")
        )
        combined = " ".join(report.warnings).lower()
        assert "tin" in combined or "marginal" in combined or "upgrade" in combined

    def test_tin_cast_iron_still_feasible(self):
        """TiN + cast iron is feasible (TiN passes the coating matrix)."""
        report = check_dry_machining(
            _spec(workpiece_material="cast-iron-grey", tool_coating="TiN")
        )
        assert report.feasible is True


# ---------------------------------------------------------------------------
# T15 — Diamond-CVD on steel warns about Fe reaction
# ---------------------------------------------------------------------------

class TestDiamondCVDOnSteel:
    def test_diamond_on_steel_warns(self):
        """Diamond-CVD on ferrous material must trigger carbon-diffusion warning."""
        report = check_dry_machining(
            _spec(workpiece_material="steel-low-carbon", tool_coating="diamond-CVD")
        )
        combined = " ".join(report.warnings).lower()
        assert "diamond" in combined or "carbon" in combined or "iron" in combined

    def test_diamond_on_steel_not_feasible(self):
        """Diamond-CVD on steel should NOT be feasible."""
        report = check_dry_machining(
            _spec(workpiece_material="steel-low-carbon", tool_coating="diamond-CVD")
        )
        assert report.feasible is False


# ---------------------------------------------------------------------------
# T16 — max_vc_dry_m_per_min is 0 for non-feasible materials
# ---------------------------------------------------------------------------

class TestMaxVcDry:
    def test_max_vc_zero_for_aluminum(self):
        """Aluminum wrought: max_vc_dry = 0 (dry not recommended at any speed)."""
        report = check_dry_machining(
            _spec(workpiece_material="aluminum-wrought", tool_coating="uncoated")
        )
        assert report.max_vc_dry_m_per_min == 0.0

    def test_max_vc_positive_for_cast_iron(self):
        """Grey cast iron: max_vc_dry should be > 0."""
        report = check_dry_machining(
            _spec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=150.0,
            )
        )
        assert report.max_vc_dry_m_per_min > 0

    def test_max_vc_dry_absolute_limit_for_cast_iron(self):
        """max_vc_dry for grey cast iron is the Sandvik catalogue upper limit (400 m/min).

        The absolute limit is material-specific (Sandvik Coromant 2024) and does NOT
        scale with the input vc — it is independent of the requested cutting speed.
        """
        report = check_dry_machining(
            _spec(
                workpiece_material="cast-iron-grey",
                tool_coating="TiAlN",
                vc_m_per_min=200.0,
            )
        )
        # Sandvik §5: grey cast iron absolute dry vc upper limit = 400 m/min
        assert report.max_vc_dry_m_per_min == pytest.approx(400.0, abs=1.0)
