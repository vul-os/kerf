"""
Tests for kerf_cam.chip_load_validate — catalog-range chip-load validator.

References
----------
* Sandvik CoroPlus Milling Technical Guide (2024)
* Kennametal Milling Application Guide (2024)
* Harvey Tool Speeds & Feeds (2024)
* MH 31e §1136
"""

from __future__ import annotations

import math
import pytest

from kerf_cam.chip_load_validate import (
    ChipLoadReport,
    ChipLoadSpec,
    validate_chip_load,
    VALID_MATERIALS,
    _FZ_RANGES,
    _RUBBING_THRESHOLD_FRAC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**kwargs) -> ChipLoadSpec:
    """Build a ChipLoadSpec with safe defaults; caller overrides via kwargs."""
    defaults = dict(
        material="steel-1018",
        tool_diameter_mm=6.0,
        num_flutes=2,
        vc_m_per_min=120.0,
        fz_mm_per_tooth=0.06,
        ae_mm=6.0,       # full-width slot, ae == D → no thinning
        ap_mm=3.0,
        tool_coating="TiAlN",
    )
    defaults.update(kwargs)
    return ChipLoadSpec(**defaults)


# ---------------------------------------------------------------------------
# T1 — Spec-mandated golden scenario: 6mm 2F, vc=120 m/min, fz=0.06 in 1018
#        steel, ae=6mm (full slot). Expected: in_range=True, no thinning.
# ---------------------------------------------------------------------------

class TestGoldenSteelFullSlot:
    def test_in_range_true(self):
        """fz=0.06 in steel-1018, 6mm, full slot must be in catalog range."""
        report = validate_chip_load(_spec())
        assert report.in_range is True

    def test_no_chip_thinning_full_slot(self):
        """ae = D → thinning_factor must equal 1.0."""
        report = validate_chip_load(_spec())
        assert report.chip_thinning_factor == pytest.approx(1.0)

    def test_effective_fz_equals_nominal_when_no_thinning(self):
        """effective_fz = fz when thinning_factor = 1.0."""
        spec = _spec(fz_mm_per_tooth=0.06)
        report = validate_chip_load(spec)
        assert report.effective_fz_mm == pytest.approx(0.06, abs=1e-9)

    def test_no_thinning_warning_in_full_slot(self):
        """No chip-thinning warning when ae = D."""
        report = validate_chip_load(_spec())
        thinning_warnings = [w for w in report.warning_messages if "Chip thinning" in w]
        assert len(thinning_warnings) == 0

    def test_rpm_formula(self):
        """rpm = vc × 1000 / (π × D) for default spec."""
        spec = _spec()
        expected_n = spec.vc_m_per_min * 1000.0 / (math.pi * spec.tool_diameter_mm)
        report = validate_chip_load(spec)
        assert report.rpm_n == pytest.approx(expected_n, rel=1e-4)

    def test_feed_formula(self):
        """feed = fz × flutes × n."""
        spec = _spec()
        n = spec.vc_m_per_min * 1000.0 / (math.pi * spec.tool_diameter_mm)
        expected_feed = spec.fz_mm_per_tooth * spec.num_flutes * n
        report = validate_chip_load(spec)
        assert report.feed_mm_per_min == pytest.approx(expected_feed, rel=1e-4)


# ---------------------------------------------------------------------------
# T2 — Chip-thinning scenario: 6mm 2F, vc=120, fz=0.06, ae=1mm (light radial).
#        Thinning factor = D/(2×ae) = 6/(2×1) = 3.0; effective_fz = 0.18 mm
#        → steel-1018 6mm max ~0.08 → over-feed warning expected.
# ---------------------------------------------------------------------------

class TestChipThinningLightRadial:
    def _report(self) -> ChipLoadReport:
        return validate_chip_load(_spec(ae_mm=1.0, fz_mm_per_tooth=0.06))

    def test_thinning_factor_is_3(self):
        """D/(2·ae) = 6/(2×1) = 3.0."""
        report = self._report()
        assert report.chip_thinning_factor == pytest.approx(3.0)

    def test_effective_fz_is_018(self):
        """effective_fz = 0.06 × 3.0 = 0.18 mm/tooth."""
        report = self._report()
        assert report.effective_fz_mm == pytest.approx(0.18, abs=1e-9)

    def test_chip_thinning_warning_present(self):
        """Thinning warning must be in warning_messages."""
        report = self._report()
        assert any("Chip thinning" in w for w in report.warning_messages)

    def test_over_feed_warning_present(self):
        """effective_fz=0.18 > fz_max=0.08 for steel-1018 6mm → OVER-FEED warn."""
        report = self._report()
        assert any("OVER-FEED" in w for w in report.warning_messages)

    def test_in_range_false(self):
        """0.18 mm/tooth exceeds max for 6mm steel-1018 → in_range False."""
        report = self._report()
        assert report.in_range is False


# ---------------------------------------------------------------------------
# T3 — Very light feed (rubbing): fz=0.01 → in_range False, rubbing warn.
# ---------------------------------------------------------------------------

class TestRubbingTooLightFeed:
    def _report(self) -> ChipLoadReport:
        # Full slot ae=D so no thinning; fz=0.01 is very low
        return validate_chip_load(_spec(fz_mm_per_tooth=0.01, ae_mm=6.0))

    def test_in_range_false(self):
        """fz=0.01 below minimum for steel-1018 6mm → in_range False."""
        report = self._report()
        assert report.in_range is False

    def test_rubbing_warning_present(self):
        """RUBBING warning present when fz far below threshold."""
        report = self._report()
        assert any("RUBBING" in w for w in report.warning_messages)

    def test_no_thinning_factor(self):
        """ae=D → thinning_factor=1.0 even for rubbing scenario."""
        report = self._report()
        assert report.chip_thinning_factor == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# T4 — Aluminum 6061 fz=0.15: in_range True (6mm bucket: 0.06–0.15).
# ---------------------------------------------------------------------------

class TestAluminum6061InRange:
    def test_in_range_true(self):
        """fz=0.15 for aluminum-6061 6mm end-mill: in_range True (range 0.06–0.15)."""
        spec = _spec(
            material="aluminum-6061",
            fz_mm_per_tooth=0.15,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is True

    def test_no_over_feed_warning(self):
        """fz=0.15 at boundary → no over-feed warning."""
        spec = _spec(
            material="aluminum-6061",
            fz_mm_per_tooth=0.15,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert not any("OVER-FEED" in w for w in report.warning_messages)

    def test_aluminum_lower_fz_below_min(self):
        """fz=0.03 for aluminum-6061 6mm → below min 0.06 → in_range False."""
        spec = _spec(
            material="aluminum-6061",
            fz_mm_per_tooth=0.03,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is False


# ---------------------------------------------------------------------------
# T5 — Titanium Ti6Al4V strict range.
# ---------------------------------------------------------------------------

class TestTitaniumRange:
    def test_ti_fz_in_range(self):
        """fz=0.04 for titanium-Ti6Al4V 6mm → in catalog range 0.015–0.040."""
        spec = _spec(
            material="titanium-Ti6Al4V",
            fz_mm_per_tooth=0.04,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is True

    def test_ti_fz_too_high(self):
        """fz=0.10 for titanium-Ti6Al4V 6mm → exceeds max 0.040 → False."""
        spec = _spec(
            material="titanium-Ti6Al4V",
            fz_mm_per_tooth=0.10,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is False
        assert any("OVER-FEED" in w for w in report.warning_messages)

    def test_ti_rubbing_very_low(self):
        """fz=0.001 for titanium → far below rubbing threshold → rubbing warn."""
        spec = _spec(
            material="titanium-Ti6Al4V",
            fz_mm_per_tooth=0.001,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        fz_min = _FZ_RANGES[("titanium-Ti6Al4V", "sm")][0]
        assert report.effective_fz_mm < _RUBBING_THRESHOLD_FRAC * fz_min
        assert any("RUBBING" in w for w in report.warning_messages)


# ---------------------------------------------------------------------------
# T6 — Stainless 304: under-feed (not rubbing) warning.
# ---------------------------------------------------------------------------

class TestStainless304:
    def test_stainless_in_range(self):
        """fz=0.04 for stainless-304 6mm: in range 0.018–0.045."""
        spec = _spec(
            material="stainless-304",
            fz_mm_per_tooth=0.04,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is True

    def test_stainless_under_feed_not_rubbing(self):
        """fz=0.016 → below min 0.018 but above rubbing threshold (0.6×0.018=0.0108)."""
        spec = _spec(
            material="stainless-304",
            fz_mm_per_tooth=0.016,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is False
        # Should have under-feed warning but NOT rubbing warning
        warnings_text = " ".join(report.warning_messages)
        assert "RUBBING" not in warnings_text
        assert "Under-feed" in warnings_text or "under-feed" in warnings_text.lower()


# ---------------------------------------------------------------------------
# T7 — Cast iron and plastic: wide tolerance.
# ---------------------------------------------------------------------------

class TestCastIronAndPlastic:
    def test_cast_iron_high_fz_in_range(self):
        """fz=0.15 for cast-iron-grey 6mm: in range 0.040–0.110? Exceeds max."""
        spec = _spec(
            material="cast-iron-grey",
            fz_mm_per_tooth=0.08,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is True

    def test_plastic_high_fz_in_range(self):
        """fz=0.12 for plastic-acetal 6mm: in range 0.040–0.150."""
        spec = _spec(
            material="plastic-acetal",
            fz_mm_per_tooth=0.12,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is True


# ---------------------------------------------------------------------------
# T8 — Thinning factor boundary: ae = D/2 exactly → factor = 1.0.
# ---------------------------------------------------------------------------

class TestThinningBoundary:
    def test_ae_half_D_no_thinning(self):
        """ae = D/2 exactly: thinning_factor = 1.0 (boundary in ae >= D/2 branch)."""
        spec = _spec(ae_mm=3.0, tool_diameter_mm=6.0)
        report = validate_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(1.0)

    def test_ae_just_below_half_D_thinning(self):
        """ae slightly below D/2: thinning factor > 1.0."""
        spec = _spec(ae_mm=2.99, tool_diameter_mm=6.0)
        report = validate_chip_load(spec)
        assert report.chip_thinning_factor > 1.0

    def test_thinning_factor_formula(self):
        """D/(2·ae) = 6/(2·2) = 1.5 for ae=2mm, D=6mm."""
        spec = _spec(ae_mm=2.0, tool_diameter_mm=6.0)
        report = validate_chip_load(spec)
        assert report.chip_thinning_factor == pytest.approx(1.5, abs=1e-6)


# ---------------------------------------------------------------------------
# T9 — Diameter bucket scaling: 12mm endmill gets "md" range, not "sm".
# ---------------------------------------------------------------------------

class TestDiameterBucketScaling:
    def test_12mm_steel_uses_md_range(self):
        """12mm tool maps to 'md' bucket (6 < D <= 12); steel-1018 md range 0.05–0.10."""
        spec = _spec(
            tool_diameter_mm=12.0,
            fz_mm_per_tooth=0.08,
            ae_mm=12.0,
        )
        report = validate_chip_load(spec)
        assert report.recommended_fz_range_mm == pytest.approx((0.050, 0.100))
        assert report.in_range is True

    def test_3mm_steel_uses_xs_range(self):
        """3mm tool maps to 'xs' bucket (D <= 3); steel-1018 xs range 0.015–0.040."""
        spec = _spec(
            tool_diameter_mm=3.0,
            fz_mm_per_tooth=0.025,
            ae_mm=3.0,
        )
        report = validate_chip_load(spec)
        assert report.recommended_fz_range_mm == pytest.approx((0.015, 0.040))
        assert report.in_range is True


# ---------------------------------------------------------------------------
# T10 — Return type and caveat content.
# ---------------------------------------------------------------------------

class TestReturnTypeAndCaveat:
    def test_returns_chip_load_report(self):
        """validate_chip_load returns ChipLoadReport."""
        report = validate_chip_load(_spec())
        assert isinstance(report, ChipLoadReport)

    def test_honest_caveat_nonempty(self):
        """honest_caveat must be a non-empty string."""
        report = validate_chip_load(_spec())
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 0

    def test_caveat_mentions_deflection(self):
        """Caveat must mention tool deflection."""
        report = validate_chip_load(_spec())
        assert "deflection" in report.honest_caveat.lower()

    def test_caveat_mentions_catalog(self):
        """Caveat must mention catalog source."""
        report = validate_chip_load(_spec())
        caveat_lower = report.honest_caveat.lower()
        assert "sandvik" in caveat_lower or "kennametal" in caveat_lower

    def test_caveat_mentions_runout(self):
        """Caveat must mention runout."""
        report = validate_chip_load(_spec())
        assert "runout" in report.honest_caveat.lower()

    def test_warning_messages_is_list(self):
        """warning_messages must be a list."""
        report = validate_chip_load(_spec())
        assert isinstance(report.warning_messages, list)

    def test_recommended_range_is_tuple_two_floats(self):
        """recommended_fz_range_mm must be a 2-tuple of floats."""
        report = validate_chip_load(_spec())
        rng = report.recommended_fz_range_mm
        assert len(rng) == 2
        assert rng[0] < rng[1]


# ---------------------------------------------------------------------------
# T11 — Input validation / error handling.
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_invalid_material_raises(self):
        with pytest.raises(ValueError, match="material"):
            ChipLoadSpec(
                material="unobtanium",
                tool_diameter_mm=6.0,
                num_flutes=2,
                vc_m_per_min=120.0,
                fz_mm_per_tooth=0.06,
                ae_mm=6.0,
                ap_mm=3.0,
            )

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="tool_diameter_mm"):
            ChipLoadSpec(
                material="steel-1018",
                tool_diameter_mm=0.0,
                num_flutes=2,
                vc_m_per_min=120.0,
                fz_mm_per_tooth=0.06,
                ae_mm=0.0,
                ap_mm=3.0,
            )

    def test_ae_exceeds_diameter_raises(self):
        with pytest.raises(ValueError, match="ae_mm"):
            ChipLoadSpec(
                material="steel-1018",
                tool_diameter_mm=6.0,
                num_flutes=2,
                vc_m_per_min=120.0,
                fz_mm_per_tooth=0.06,
                ae_mm=7.0,
                ap_mm=3.0,
            )

    def test_zero_flutes_raises(self):
        with pytest.raises(ValueError, match="num_flutes"):
            ChipLoadSpec(
                material="steel-1018",
                tool_diameter_mm=6.0,
                num_flutes=0,
                vc_m_per_min=120.0,
                fz_mm_per_tooth=0.06,
                ae_mm=6.0,
                ap_mm=3.0,
            )

    def test_zero_vc_raises(self):
        with pytest.raises(ValueError, match="vc_m_per_min"):
            ChipLoadSpec(
                material="steel-1018",
                tool_diameter_mm=6.0,
                num_flutes=2,
                vc_m_per_min=0.0,
                fz_mm_per_tooth=0.06,
                ae_mm=6.0,
                ap_mm=3.0,
            )

    def test_zero_ap_raises(self):
        with pytest.raises(ValueError, match="ap_mm"):
            ChipLoadSpec(
                material="steel-1018",
                tool_diameter_mm=6.0,
                num_flutes=2,
                vc_m_per_min=120.0,
                fz_mm_per_tooth=0.06,
                ae_mm=6.0,
                ap_mm=0.0,
            )


# ---------------------------------------------------------------------------
# T12 — High engagement warning (ae >= D/2 AND fz near upper end).
# ---------------------------------------------------------------------------

class TestHighEngagementWarning:
    def test_high_engagement_warn_present(self):
        """ae = D (full slot), fz near fz_max → high-engagement warning."""
        # steel-1018, 6mm, ae=6 (full slot), fz just below max 0.08
        spec = _spec(fz_mm_per_tooth=0.075, ae_mm=6.0)
        report = validate_chip_load(spec)
        # Should be in range (fz=0.075 < 0.08) and warn about high engagement
        engagement_warns = [w for w in report.warning_messages if "High engagement" in w]
        assert len(engagement_warns) >= 1

    def test_moderate_fz_no_engagement_warn(self):
        """ae = D but fz in mid-range → no high-engagement warning."""
        spec = _spec(fz_mm_per_tooth=0.05, ae_mm=6.0)
        report = validate_chip_load(spec)
        engagement_warns = [w for w in report.warning_messages if "High engagement" in w]
        assert len(engagement_warns) == 0


# ---------------------------------------------------------------------------
# T13 — steel-4140-soft distinct from steel-1018 ranges.
# ---------------------------------------------------------------------------

class TestSteel4140SoftRanges:
    def test_4140_tighter_range_than_1018(self):
        """steel-4140-soft has lower fz_max than steel-1018 for same diameter."""
        min_1018, max_1018 = _FZ_RANGES[("steel-1018", "sm")]
        min_4140, max_4140 = _FZ_RANGES[("steel-4140-soft", "sm")]
        assert max_4140 < max_1018

    def test_4140_fz_008_in_range(self):
        """fz=0.05 for steel-4140-soft 6mm is in range (0.020–0.060)."""
        spec = _spec(
            material="steel-4140-soft",
            fz_mm_per_tooth=0.05,
            ae_mm=6.0,
        )
        report = validate_chip_load(spec)
        assert report.in_range is True
