"""
Tests for kerf_cad_core.jewelry.print_presets

≥25 hermetic unit tests covering:
  1.  printer_preset by (brand, model) — envelope, materials, technology
  2.  printer_preset unknown-printer error path
  3.  recommended_orientation — rotates to minimise layer lines on top face
  4.  recommended_orientation — Z axis choice for 'auto' (largest X-Y area)
  5.  recommended_orientation — bad AABB rejected
  6.  support_plan — count proportional to underside area
  7.  support_plan — exclusion zones remove contacts
  8.  support_plan — bad geometry rejected
  9.  cure_schedule — exposure time monotone in layer thickness (DLP printers)
  10. cure_schedule — unknown material error path
  11. cure_schedule — wax-jet returns no UV cure
  12. cure_schedule — LFS printers have no per-layer exposure_s
  13. cure_schedule — printer compatibility warning
  14. burnout_schedule — resin has correct phases (warm_up/dewax/preheat/hold)
  15. burnout_schedule — wax has correct phases with shorter durations
  16. burnout_schedule — unknown pattern_type error path
  17. burnout_schedule — total_duration_min is sum of stage durations
  18. burnout_schedule — peak_temp_c is 732 for both schedules
  19. Data integrity — all _PRINTER_DB entries have required keys
  20. Data integrity — all supported_materials keys exist in _CURE_DB
  21. Data integrity — all _MATERIAL_LABELS keys exist in _CURE_DB
  22. Solidscape S300 preset — wax-jet technology, no UV cure
  23. EnvisionTEC Micro+ preset — DLP, 16 µm XY resolution
  24. Formlabs Form 3B+ preset — LFS technology, correct envelope
  25. B9 Creator preset — DLP, b9_yellow and b9_blue materials
  26. support_plan — larger piece has more or equal support contacts
  27. LLM tool runners — ok_payload / err_payload round-trip (import check)
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.jewelry.print_presets import (
    # public API
    printer_preset,
    recommended_orientation,
    support_plan,
    cure_schedule,
    burnout_schedule,
    # internal DB tables (for data-integrity tests)
    _PRINTER_DB,
    _CURE_DB,
    _MATERIAL_LABELS,
    _MATERIAL_IS_WAX_JET,
    # LLM tool runners
    run_jewelry_print_preset,
    run_jewelry_print_orientation,
    run_jewelry_support_plan,
    run_jewelry_cure_schedule,
    run_jewelry_burnout_schedule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro) -> dict:
    """Run async coroutine and return parsed JSON dict."""
    raw = asyncio.new_event_loop().run_until_complete(coro)
    return json.loads(raw)


def _make_ctx():
    """Minimal stub context (tool runners accept it but don't use it)."""
    import uuid
    from kerf_core.utils.context import ProjectCtx

    class _FakePool:
        def fetchone(self, *a):
            return None
        def execute(self, *a):
            pass

    return ProjectCtx(
        pool=_FakePool(),
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )


def _ok(result: dict) -> bool:
    return "error" not in result and "code" not in result


# Small AABB helpers
_RING_AABB = (0.0, 0.0, 0.0, 20.0, 20.0, 8.0)      # 20×20×8 mm ring-like piece
_SLAB_AABB = (0.0, 0.0, 0.0, 50.0, 30.0, 5.0)       # 50×30×5 mm flat slab


# ============================================================================
# 1. printer_preset — lookup by (brand, model)
# ============================================================================

class TestPrinterPreset:

    def test_formlabs_form3bplus_returns_preset(self):
        p = printer_preset("Formlabs", "Form 3B+")
        assert "error" not in p
        assert p["brand"] == "Formlabs"
        assert p["model"] == "Form 3B+"

    def test_formlabs_form3bplus_envelope(self):
        """Form 3B+ build envelope must be 145 × 145 × 185 mm."""
        p = printer_preset("Formlabs", "Form 3B+")
        x, y, z = p["build_envelope_mm"]
        assert x == pytest.approx(145.0, abs=1.0)
        assert y == pytest.approx(145.0, abs=1.0)
        assert z == pytest.approx(185.0, abs=1.0)

    def test_formlabs_form3bplus_technology_is_lfs(self):
        p = printer_preset("Formlabs", "Form 3B+")
        assert p["technology"] == "lfs"

    def test_formlabs_form3bplus_supported_castable_materials(self):
        p = printer_preset("Formlabs", "Form 3B+")
        assert "castable_wax_40" in p["supported_materials"]
        assert "castable_blue_resin" in p["supported_materials"]
        assert "castable_tough_resin" in p["supported_materials"]

    def test_formlabs_form4b_returns_preset(self):
        p = printer_preset("formlabs", "form 4b")   # case-insensitive
        assert "error" not in p
        assert p["technology"] == "lfs"

    def test_envisiontec_microplus_dlp(self):
        """EnvisionTEC Micro+ is DLP with 16 µm XY resolution."""
        p = printer_preset("EnvisionTEC", "Micro+")
        assert "error" not in p
        assert p["technology"] == "dlp"
        assert p["xy_resolution_um"] == 16

    def test_envisiontec_ultra_dlp_easy_cast(self):
        p = printer_preset("EnvisionTEC", "Ultra")
        assert "error" not in p
        assert "easy_cast_2_0" in p["supported_materials"]
        assert "ec500" in p["supported_materials"]

    def test_b9creator_returns_preset(self):
        """B9 Creator is DLP; supports b9_yellow and b9_blue."""
        p = printer_preset("B9Creations", "B9 Creator")
        assert "error" not in p
        assert p["technology"] == "dlp"
        assert "b9_yellow" in p["supported_materials"]
        assert "b9_blue" in p["supported_materials"]

    def test_solidscape_s300_wax_jet(self):
        """Solidscape S300 is wax_jet; no UV cure."""
        p = printer_preset("Solidscape", "S300")
        assert "error" not in p
        assert p["technology"] == "wax_jet"
        assert p["uv_post_cure_s"] is None
        assert "solidscape_s300_wax" in p["supported_materials"]

    def test_solidscape_t200_wax_jet(self):
        p = printer_preset("Solidscape", "T200")
        assert "error" not in p
        assert p["technology"] == "wax_jet"
        assert "solidscape_t200_wax" in p["supported_materials"]

    def test_unknown_printer_returns_error(self):
        """An unrecognised printer returns UNKNOWN_PRINTER code, never raises."""
        result = printer_preset("Acme", "SuperPrinter 9000")
        assert "error" in result
        assert result["code"] == "UNKNOWN_PRINTER"
        assert "known_printers" in result
        assert len(result["known_printers"]) > 0

    def test_case_insensitive_lookup(self):
        """Brand/model lookup is case-insensitive."""
        p1 = printer_preset("formlabs", "form 3b+")
        p2 = printer_preset("FORMLABS", "FORM 3B+")
        assert p1["brand"] == p2["brand"]


# ============================================================================
# 2. recommended_orientation
# ============================================================================

class TestRecommendedOrientation:

    def test_top_axis_hint_gives_y_build_axis(self):
        """'top' hint → build axis Y (crown face parallel to platform)."""
        result = recommended_orientation(_RING_AABB, "top")
        assert "error" not in result
        assert result["recommended_axis"] == "Y"

    def test_front_axis_hint_gives_x_build_axis(self):
        """'front' hint → build axis X (signet face parallel to platform)."""
        result = recommended_orientation(_RING_AABB, "front")
        assert "error" not in result
        assert result["recommended_axis"] == "X"

    def test_auto_picks_largest_xy_area_axis(self):
        """'auto' picks the build axis that maximises X-Y projected area."""
        # Slab: dx=50, dy=30, dz=5
        # Build X → cross-section Y×Z = 30×5 = 150
        # Build Y → cross-section X×Z = 50×5 = 250
        # Build Z → cross-section X×Y = 50×30 = 1500 ← largest
        result = recommended_orientation(_SLAB_AABB, "auto")
        assert result["recommended_axis"] == "Z"

    def test_ring_top_orientation_rotation_applied(self):
        """Top orientation rotates 90° around X."""
        result = recommended_orientation(_RING_AABB, "top")
        rx, ry, rz = result["rotation_deg"]
        assert rx == pytest.approx(90.0, abs=0.1)

    def test_z_height_positive(self):
        result = recommended_orientation(_RING_AABB, "top")
        assert result["z_height_mm"] > 0

    def test_xy_span_positive(self):
        result = recommended_orientation(_RING_AABB, "top")
        w, d = result["xy_span_mm"]
        assert w > 0
        assert d > 0

    def test_layer_count_estimate_positive(self):
        result = recommended_orientation(_RING_AABB, "top")
        assert result["layer_count_estimate"] > 0

    def test_layer_count_consistent_with_z_height(self):
        """layer_count_estimate ≈ ceil(z_height / 0.025)."""
        result = recommended_orientation(_RING_AABB, "top")
        expected = math.ceil(result["z_height_mm"] / 0.025)
        assert result["layer_count_estimate"] == expected

    def test_bad_aabb_zero_span_returns_error(self):
        """AABB with zero span is rejected without raising."""
        result = recommended_orientation((0.0, 0.0, 0.0, 0.0, 10.0, 10.0), "top")
        assert "error" in result
        assert result["code"] == "BAD_AABB"

    def test_crown_alias_same_as_top(self):
        """'crown' is an alias for 'top' — same build axis result."""
        r_top = recommended_orientation(_RING_AABB, "top")
        r_crown = recommended_orientation(_RING_AABB, "crown")
        assert r_top["recommended_axis"] == r_crown["recommended_axis"]


# ============================================================================
# 3. support_plan
# ============================================================================

class TestSupportPlan:

    def _default_printer(self):
        return printer_preset("Formlabs", "Form 3B+")

    def test_basic_plan_returns_contacts(self):
        p = self._default_printer()
        result = support_plan(_RING_AABB, p)
        assert "error" not in result
        assert result["support_count"] >= 1

    def test_support_count_proportional_to_area(self):
        """Larger underside area at same density → at least as many contacts."""
        p = self._default_printer()
        # Small piece: 10×10 underside
        small_aabb = (0.0, 0.0, 0.0, 10.0, 10.0, 5.0)
        # Large piece: 40×40 underside (4× area)
        large_aabb = (0.0, 0.0, 0.0, 40.0, 40.0, 5.0)
        r_small = support_plan(small_aabb, p, density_pct=20.0)
        r_large = support_plan(large_aabb, p, density_pct=20.0)
        assert r_large["support_count"] > r_small["support_count"]

    def test_exclusion_zones_reduce_contacts(self):
        """Adding an exclusion zone reduces support count."""
        p = self._default_printer()
        r_no_excl = support_plan(_RING_AABB, p, density_pct=20.0)
        # Exclude a large circle in the centre
        excl = [{"cx_mm": 10.0, "cy_mm": 10.0, "radius_mm": 8.0, "label": "stone"}]
        r_excl = support_plan(_RING_AABB, p, density_pct=20.0, exclusion_zones=excl)
        assert r_excl["support_count"] <= r_no_excl["support_count"]
        assert r_excl["exclusion_zones_used"] == 1

    def test_contacts_have_required_keys(self):
        p = self._default_printer()
        result = support_plan(_RING_AABB, p)
        for contact in result["contacts"]:
            for key in ("x_mm", "y_mm", "z_mm", "strut_height_mm", "strut_diameter_mm"):
                assert key in contact, f"Contact missing key: {key}"

    def test_zero_density_rejected(self):
        p = self._default_printer()
        result = support_plan(_RING_AABB, p, density_pct=0.0)
        assert "error" in result

    def test_bad_aabb_rejected(self):
        p = self._default_printer()
        result = support_plan((0.0, 0.0, 0.0, 0.0, 10.0, 5.0), p)
        assert "error" in result

    def test_strut_diameter_at_least_min_wall(self):
        """Strut diameter must not be smaller than printer min_wall_mm."""
        p = self._default_printer()
        result = support_plan(_RING_AABB, p, contact_diameter_mm=0.2)
        assert result["strut_diameter_mm"] >= p["min_wall_mm"]

    def test_solidscape_wax_jet_support_plan(self):
        """Support plan works for wax-jet printers too."""
        p = printer_preset("Solidscape", "S300")
        result = support_plan(_RING_AABB, p)
        assert "error" not in result
        assert result["support_count"] >= 1


# ============================================================================
# 4. cure_schedule
# ============================================================================

class TestCureSchedule:

    def test_easy_cast_returns_exposure_s(self):
        """DLP resin has non-None exposure_s_per_layer."""
        result = cure_schedule("easy_cast_2_0", 0.025)
        assert "error" not in result
        assert result["exposure_s_per_layer"] is not None
        assert result["exposure_s_per_layer"] > 0

    def test_exposure_monotone_in_layer_thickness(self):
        """Thicker layers require more exposure time (linear scaling)."""
        r1 = cure_schedule("easy_cast_2_0", 0.025)
        r2 = cure_schedule("easy_cast_2_0", 0.050)
        r3 = cure_schedule("easy_cast_2_0", 0.100)
        assert r2["exposure_s_per_layer"] > r1["exposure_s_per_layer"]
        assert r3["exposure_s_per_layer"] > r2["exposure_s_per_layer"]

    def test_lfs_resin_has_no_per_layer_exposure(self):
        """Formlabs LFS resins: exposure controlled by firmware, not a fixed value."""
        result = cure_schedule("castable_wax_40", 0.025)
        assert "error" not in result
        assert result["exposure_s_per_layer"] is None

    def test_lfs_resin_has_uv_post_cure(self):
        result = cure_schedule("castable_wax_40", 0.025)
        assert result["uv_post_cure_s"] is not None
        assert result["uv_post_cure_s"] > 0

    def test_wax_jet_material_is_wax_jet(self):
        """Solidscape wax: is_wax_jet True, no UV cure."""
        result = cure_schedule("solidscape_s300_wax", 0.025)
        assert "error" not in result
        assert result["is_wax_jet"] is True
        assert result["exposure_s_per_layer"] is None
        assert result["uv_post_cure_s"] is None

    def test_unknown_material_returns_error(self):
        """Unknown material returns UNKNOWN_MATERIAL code, never raises."""
        result = cure_schedule("nonexistent_resin_xyz", 0.025)
        assert "error" in result
        assert result["code"] == "UNKNOWN_MATERIAL"
        assert "known_materials" in result

    def test_zero_layer_thickness_returns_error(self):
        result = cure_schedule("easy_cast_2_0", 0.0)
        assert "error" in result

    def test_b9_yellow_scales_exposure_correctly(self):
        """B9 Yellow reference 0.030 mm @ 3.5 s → 0.060 mm @ ~7.0 s."""
        r_thin = cure_schedule("b9_yellow", 0.030)
        r_thick = cure_schedule("b9_yellow", 0.060)
        assert r_thick["exposure_s_per_layer"] == pytest.approx(
            r_thin["exposure_s_per_layer"] * 2.0, rel=0.01
        )

    def test_printer_compat_warning_for_mismatched_material(self):
        """Providing a printer that doesn't support the material triggers a warning."""
        solidscape_p = printer_preset("Solidscape", "S300")
        result = cure_schedule("easy_cast_2_0", 0.025, printer=solidscape_p)
        assert "error" not in result
        assert "WARNING" in result["printer_compatibility_note"]


# ============================================================================
# 5. burnout_schedule
# ============================================================================

class TestBurnoutSchedule:

    def test_resin_schedule_has_four_phases(self):
        result = burnout_schedule("resin")
        assert "error" not in result
        phases = [s["phase"] for s in result["stages"]]
        assert "warm_up" in phases
        assert "dewax" in phases
        assert "preheat" in phases
        assert "hold" in phases

    def test_wax_schedule_has_four_phases(self):
        result = burnout_schedule("wax")
        assert "error" not in result
        phases = [s["phase"] for s in result["stages"]]
        assert "warm_up" in phases
        assert "dewax" in phases
        assert "preheat" in phases
        assert "hold" in phases

    def test_total_duration_is_sum_of_stages(self):
        for ptype in ("resin", "wax"):
            result = burnout_schedule(ptype)
            stage_sum = sum(s["duration_min"] for s in result["stages"])
            assert result["total_duration_min"] == stage_sum

    def test_peak_temp_is_732(self):
        """Both schedules peak at 732 °C (industry standard hold temp)."""
        for ptype in ("resin", "wax"):
            result = burnout_schedule(ptype)
            assert result["peak_temp_c"] == 732

    def test_wax_shorter_than_resin(self):
        """Wax schedule is faster (less organic material) than resin schedule."""
        r_resin = burnout_schedule("resin")
        r_wax = burnout_schedule("wax")
        assert r_wax["total_duration_min"] < r_resin["total_duration_min"]

    def test_unknown_pattern_type_error(self):
        """Unknown pattern type returns UNKNOWN_PATTERN_TYPE, never raises."""
        result = burnout_schedule("metal_injection_moulding")
        assert "error" in result
        assert result["code"] == "UNKNOWN_PATTERN_TYPE"

    def test_stages_temperature_progression(self):
        """Each stage's to_c >= from_c (temperatures are non-decreasing until hold)."""
        result = burnout_schedule("resin")
        non_hold = [s for s in result["stages"] if not s["hold"]]
        for s in non_hold:
            assert s["to_c"] >= s["from_c"], f"Stage {s['phase']} has decreasing temps"

    def test_hold_stage_constant_temp(self):
        """Hold stage has from_c == to_c."""
        result = burnout_schedule("resin")
        hold_stages = [s for s in result["stages"] if s["hold"]]
        assert len(hold_stages) >= 1
        for h in hold_stages:
            assert h["from_c"] == h["to_c"]

    def test_case_insensitive_pattern_type(self):
        """'RESIN' and 'resin' both work."""
        r1 = burnout_schedule("resin")
        r2 = burnout_schedule("RESIN")
        assert r1["total_duration_min"] == r2["total_duration_min"]


# ============================================================================
# 6. Data integrity
# ============================================================================

class TestDataIntegrity:

    def test_all_printer_entries_have_required_keys(self):
        """Every entry in _PRINTER_DB has the required keys."""
        required = {
            "brand", "model", "technology", "build_envelope_mm",
            "xy_resolution_um", "layer_height_mm", "layer_height_range_mm",
            "exposure_s", "uv_post_cure_s", "supported_materials", "min_wall_mm",
        }
        for (brand, model), preset in _PRINTER_DB.items():
            missing = required - set(preset.keys())
            assert not missing, (
                f"Printer '{brand} {model}' missing keys: {missing}"
            )

    def test_all_supported_materials_in_cure_db(self):
        """Every material listed in any printer's supported_materials is in _CURE_DB."""
        for (brand, model), preset in _PRINTER_DB.items():
            for mat in preset.get("supported_materials", []):
                assert mat in _CURE_DB, (
                    f"Printer '{brand} {model}' lists material '{mat}' "
                    "which is not in _CURE_DB"
                )

    def test_all_material_labels_in_cure_db(self):
        """All keys in _MATERIAL_LABELS also exist in _CURE_DB."""
        for mat_key in _MATERIAL_LABELS:
            assert mat_key in _CURE_DB, (
                f"_MATERIAL_LABELS has '{mat_key}' but _CURE_DB does not"
            )

    def test_material_is_wax_jet_coverage(self):
        """_MATERIAL_IS_WAX_JET covers all cure-DB keys."""
        for mat_key in _CURE_DB:
            assert mat_key in _MATERIAL_IS_WAX_JET, (
                f"_MATERIAL_IS_WAX_JET missing key '{mat_key}'"
            )

    def test_build_envelope_all_positive(self):
        """All build envelopes have positive dimensions."""
        for (brand, model), preset in _PRINTER_DB.items():
            x, y, z = preset["build_envelope_mm"]
            assert x > 0 and y > 0 and z > 0, (
                f"Printer '{brand} {model}' has non-positive envelope: {x},{y},{z}"
            )

    def test_layer_height_range_valid(self):
        """layer_height_range_mm is (min, max) with min ≤ max."""
        for (brand, model), preset in _PRINTER_DB.items():
            lo, hi = preset["layer_height_range_mm"]
            assert lo <= hi, (
                f"Printer '{brand} {model}' layer_height_range is inverted: {lo}, {hi}"
            )

    def test_wax_jet_printers_have_laser_power(self):
        """Wax-jet printers must have a laser_power_mw value."""
        for (brand, model), preset in _PRINTER_DB.items():
            if preset["technology"] == "wax_jet":
                assert preset["laser_power_mw"] is not None, (
                    f"Wax-jet printer '{brand} {model}' missing laser_power_mw"
                )


# ============================================================================
# 7. LLM tool runner smoke tests
# ============================================================================

class TestLLMRunners:

    def _ctx(self):
        return _make_ctx()

    def test_run_print_preset_ok(self):
        ctx = self._ctx()
        result = _run(run_jewelry_print_preset(
            ctx,
            json.dumps({"brand": "Formlabs", "model": "Form 3B+"}).encode(),
        ))
        assert _ok(result)
        assert result["brand"] == "Formlabs"

    def test_run_print_preset_unknown_returns_error_payload(self):
        ctx = self._ctx()
        result = _run(run_jewelry_print_preset(
            ctx,
            json.dumps({"brand": "Acme", "model": "Ghost 1000"}).encode(),
        ))
        assert "error" in result or "code" in result

    def test_run_print_orientation_ok(self):
        ctx = self._ctx()
        result = _run(run_jewelry_print_orientation(
            ctx,
            json.dumps({
                "piece_aabb": list(_RING_AABB),
                "anti_stairstepping_axis": "top",
            }).encode(),
        ))
        assert _ok(result)
        assert result["recommended_axis"] == "Y"

    def test_run_support_plan_ok(self):
        ctx = self._ctx()
        result = _run(run_jewelry_support_plan(
            ctx,
            json.dumps({
                "piece_aabb": list(_RING_AABB),
                "brand": "Formlabs",
                "model": "Form 3B+",
                "density_pct": 15.0,
            }).encode(),
        ))
        assert _ok(result)
        assert result["support_count"] >= 1

    def test_run_cure_schedule_ok(self):
        ctx = self._ctx()
        result = _run(run_jewelry_cure_schedule(
            ctx,
            json.dumps({
                "material": "easy_cast_2_0",
                "layer_thickness_mm": 0.025,
            }).encode(),
        ))
        assert _ok(result)
        assert result["exposure_s_per_layer"] > 0

    def test_run_burnout_schedule_resin_ok(self):
        ctx = self._ctx()
        result = _run(run_jewelry_burnout_schedule(
            ctx,
            json.dumps({"pattern_type": "resin"}).encode(),
        ))
        assert _ok(result)
        assert result["peak_temp_c"] == 732

    def test_run_burnout_schedule_wax_ok(self):
        ctx = self._ctx()
        result = _run(run_jewelry_burnout_schedule(
            ctx,
            json.dumps({"pattern_type": "wax"}).encode(),
        ))
        assert _ok(result)
        assert len(result["stages"]) == 4
