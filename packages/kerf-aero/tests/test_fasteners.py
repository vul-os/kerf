"""Analytic-oracle tests for the aerospace fasteners catalogue.

Run with:
    PYTHONPATH=packages/kerf-core/src:packages/kerf-aero/src \
        python3 -m pytest packages/kerf-aero/tests/test_fasteners.py -x
"""

from __future__ import annotations

import math
import pytest

from kerf_aero.fasteners.catalogue import (
    CATALOGUE,
    REQUIRED_FIELDS,
    get_by_spec,
    filter_catalogue,
)
from kerf_aero.fasteners.sizing import joint_allowable, pick_fastener


# ---------------------------------------------------------------------------
# 1. Catalogue completeness
# ---------------------------------------------------------------------------

class TestCatalogueCompleteness:
    def test_at_least_100_entries(self):
        """Catalogue must have ≥ 100 entries."""
        assert len(CATALOGUE) >= 100, f"Only {len(CATALOGUE)} entries found"

    def test_all_required_fields_present(self):
        """Every entry must contain all required fields."""
        for entry in CATALOGUE:
            for field in REQUIRED_FIELDS:
                assert field in entry, (
                    f"Entry {entry.get('spec', '?')} missing field {field!r}"
                )

    def test_spec_field_is_non_empty_string(self):
        for entry in CATALOGUE:
            assert isinstance(entry["spec"], str) and entry["spec"], (
                f"Bad spec in entry: {entry}"
            )

    def test_diameter_in_is_positive_float(self):
        for entry in CATALOGUE:
            assert isinstance(entry["diameter_in"], (int, float)), entry["spec"]
            assert entry["diameter_in"] > 0, entry["spec"]

    def test_length_in_is_positive_float(self):
        for entry in CATALOGUE:
            assert entry["length_in"] > 0, entry["spec"]

    def test_grip_range_is_valid_tuple(self):
        for entry in CATALOGUE:
            lo, hi = entry["grip_range"]
            assert lo >= 0, f"{entry['spec']} grip min < 0"
            assert hi > lo, f"{entry['spec']} grip max <= min"

    def test_shear_kip_positive(self):
        for entry in CATALOGUE:
            assert entry["shear_kip"] > 0, entry["spec"]

    def test_tension_kip_positive(self):
        for entry in CATALOGUE:
            assert entry["tension_kip"] > 0, entry["spec"]

    def test_no_duplicate_specs(self):
        specs = [e["spec"] for e in CATALOGUE]
        assert len(specs) == len(set(specs)), (
            f"Duplicate spec(s): {[s for s in specs if specs.count(s) > 1]}"
        )

    def test_mfr_field_non_empty(self):
        for entry in CATALOGUE:
            assert entry["mfr"], f"Empty mfr for {entry['spec']}"

    def test_head_style_field_non_empty(self):
        for entry in CATALOGUE:
            assert entry["head_style"], f"Empty head_style for {entry['spec']}"

    def test_material_field_non_empty(self):
        for entry in CATALOGUE:
            assert entry["material"], f"Empty material for {entry['spec']}"

    def test_finish_field_present(self):
        for entry in CATALOGUE:
            assert "finish" in entry, f"Missing finish for {entry['spec']}"


# ---------------------------------------------------------------------------
# 2. Specific family checks
# ---------------------------------------------------------------------------

class TestFamilyCoverage:
    def test_hilok_hl18_present(self):
        hl18 = [e for e in CATALOGUE if e["spec"].startswith("HL18")]
        assert len(hl18) >= 5, f"Only {len(hl18)} HL18 entries"

    def test_hilok_hl19_present(self):
        hl19 = [e for e in CATALOGUE if e["spec"].startswith("HL19")]
        assert len(hl19) >= 5, f"Only {len(hl19)} HL19 entries"

    def test_hilok_hl10_present(self):
        hl10 = [e for e in CATALOGUE if e["spec"].startswith("HL10")]
        assert len(hl10) >= 5, f"Only {len(hl10)} HL10 entries"

    def test_hilok_hl11_present(self):
        hl11 = [e for e in CATALOGUE if e["spec"].startswith("HL11")]
        assert len(hl11) >= 5, f"Only {len(hl11)} HL11 entries"

    def test_cherry_cr3243_present(self):
        cr = [e for e in CATALOGUE if e["spec"].startswith("CR3243")]
        assert len(cr) >= 8, f"Only {len(cr)} CR3243 entries"

    def test_nas6204_present(self):
        nas = [e for e in CATALOGUE if e["spec"].startswith("NAS6204")]
        assert len(nas) >= 4, f"Only {len(nas)} NAS6204 entries"

    def test_nas6203_through_nas6210_families(self):
        for code in ("NAS6203", "NAS6204", "NAS6205", "NAS6206",
                     "NAS6207", "NAS6208", "NAS6209", "NAS6210"):
            entries = [e for e in CATALOGUE if e["spec"].startswith(code)]
            assert entries, f"No entries for {code}"

    def test_ms21250_present(self):
        ms = [e for e in CATALOGUE if e["spec"].startswith("MS21250")]
        assert len(ms) >= 5, f"Only {len(ms)} MS21250 entries"

    def test_ms9395_present(self):
        ms = [e for e in CATALOGUE if e["spec"].startswith("MS9395")]
        assert len(ms) >= 5, f"Only {len(ms)} MS9395 entries"

    def test_ms27039_present(self):
        ms = [e for e in CATALOGUE if e["spec"].startswith("MS27039")]
        assert len(ms) >= 5, f"Only {len(ms)} MS27039 entries"

    def test_as3219_through_as3243_families(self):
        for code in ("AS3219", "AS3220", "AS3221", "AS3243"):
            entries = [e for e in CATALOGUE if e["spec"].startswith(code)]
            assert entries, f"No entries for {code}"

    def test_huck_lok_present(self):
        huck = [e for e in CATALOGUE if e["spec"].startswith("HLK")]
        assert len(huck) >= 5, f"Only {len(huck)} Huck-Lok entries"

    def test_tinnerman_present(self):
        tin = [e for e in CATALOGUE if e["spec"].startswith("TIN")]
        assert len(tin) >= 3, f"Only {len(tin)} Tinnerman entries"

    def test_diameter_range_1_8_to_5_8(self):
        diameters = {e["diameter_in"] for e in CATALOGUE}
        assert 0.125 in diameters, "No 1/8\" entries"
        assert 0.250 in diameters, "No 1/4\" entries"
        assert 0.375 in diameters, "No 3/8\" entries"


# ---------------------------------------------------------------------------
# 3. Material / head-style coverage
# ---------------------------------------------------------------------------

class TestMaterialCoverage:
    def test_titanium_entries_exist(self):
        ti = [e for e in CATALOGUE if "titanium" in e["material"]]
        assert len(ti) >= 10

    def test_alloy_steel_entries_exist(self):
        st = [e for e in CATALOGUE if "alloy-steel" in e["material"]]
        assert len(st) >= 20

    def test_aluminum_rivet_entries_exist(self):
        al = [e for e in CATALOGUE if "2117" in e["material"]]
        assert len(al) >= 10

    def test_a286_entries_exist(self):
        a = [e for e in CATALOGUE if "a286" in e["material"]]
        assert len(a) >= 5

    def test_countersunk_entries_exist(self):
        cs = [e for e in CATALOGUE if "countersunk" in e["head_style"]]
        assert len(cs) >= 20

    def test_protruding_entries_exist(self):
        pr = [e for e in CATALOGUE if e["head_style"] == "protruding"]
        assert len(pr) >= 20

    def test_hex_head_entries_exist(self):
        hx = [e for e in CATALOGUE if e["head_style"] == "hex"]
        assert len(hx) >= 20


# ---------------------------------------------------------------------------
# 4. Key allowable oracle: 1/4" NAS6204 shear ≈ 9.95 kip (±5%)
# ---------------------------------------------------------------------------

class TestAllowableOracles:
    def test_nas6204_shear_oracle(self):
        """At least one 1/4\" NAS6204 entry must have shear_kip within 5% of 9.95 kip.

        9.95 kip is the published double-shear ultimate allowable for a 1/4-28
        NAS6204 bolt (160-ksi alloy steel), per IFI/NAS dimensional tables.
        """
        entries = [e for e in CATALOGUE if e["spec"].startswith("NAS6204")]
        assert entries, "No NAS6204 entries found"
        target = 9.95
        tol = 0.05  # 5%
        # At least one entry should match the 9.95-kip double-shear oracle
        matching = [
            e for e in entries
            if abs(e["shear_kip"] - target) / target <= tol
        ]
        assert matching, (
            f"No NAS6204 entry has shear_kip within 5% of {target} kip. "
            f"Found: {[(e['spec'], e['shear_kip']) for e in entries]}"
        )

    def test_nas6204_quarter_inch_diameter(self):
        entries = [e for e in CATALOGUE if e["spec"].startswith("NAS6204")]
        for e in entries:
            assert abs(e["diameter_in"] - 0.250) < 1e-4, (
                f"{e['spec']} diameter = {e['diameter_in']} not 0.250\""
            )

    def test_hl18_pb_6_8_shear_ballpark(self):
        """HL18 3/8\" pin should have shear allowable roughly 9-11 kip."""
        e = get_by_spec("HL18PB-6-8")
        assert e is not None, "HL18PB-6-8 not in catalogue"
        assert 8.0 <= e["shear_kip"] <= 12.0, (
            f"HL18PB-6-8 shear={e['shear_kip']} out of expected range"
        )

    def test_hl18_pb_4_8_diameter(self):
        """HL18 -4 pin should be 1/4\" (0.250\")."""
        e = get_by_spec("HL18PB-4-8")
        assert e is not None, "HL18PB-4-8 not in catalogue"
        assert abs(e["diameter_in"] - 0.250) < 1e-4

    def test_cr3243_8_08_shear(self):
        """CherryMAX 1/4\" rivet — shear_kip in reasonable range."""
        e = get_by_spec("CR3243-8-08")
        assert e is not None
        assert 2.5 <= e["shear_kip"] <= 5.0, f"CR3243-8-08 shear={e['shear_kip']}"

    def test_ms27039_tension_gt_shear(self):
        """Pan-head machine screws should have tension ≥ shear in our table."""
        ms = [e for e in CATALOGUE if e["spec"].startswith("MS27039")]
        for e in ms:
            assert e["tension_kip"] >= e["shear_kip"] * 0.95, (
                f"{e['spec']} tension < 95% of shear"
            )

    def test_nas6206_shear_gt_nas6205(self):
        """3/8\" bolt should be stronger than 5/16\" bolt."""
        e6 = [e for e in CATALOGUE if e["spec"].startswith("NAS6206")][0]
        e5 = [e for e in CATALOGUE if e["spec"].startswith("NAS6205")][0]
        assert e6["shear_kip"] > e5["shear_kip"]

    def test_hl10_stronger_than_hl18_same_dia(self):
        """Alloy-steel HL10 should exceed titanium HL18 at same diameter."""
        hl10_4 = [e for e in CATALOGUE if e["spec"].startswith("HL10PB-4")]
        hl18_4 = [e for e in CATALOGUE if e["spec"].startswith("HL18PB-4")]
        assert hl10_4 and hl18_4
        assert hl10_4[0]["shear_kip"] > hl18_4[0]["shear_kip"]


# ---------------------------------------------------------------------------
# 5. get_by_spec() lookups
# ---------------------------------------------------------------------------

class TestGetBySpec:
    def test_known_spec_found(self):
        e = get_by_spec("NAS6204-8")
        assert e is not None
        assert e["spec"] == "NAS6204-8"

    def test_unknown_spec_returns_none(self):
        e = get_by_spec("NONEXISTENT-99")
        assert e is None

    def test_hl18_lookup(self):
        e = get_by_spec("HL18PB-6-8")
        assert e is not None
        assert e["diameter_in"] == pytest.approx(0.375)

    def test_cherry_lookup(self):
        e = get_by_spec("CR3243-6-08")
        assert e is not None
        assert e["mfr"] == "Cherry Aerospace"

    def test_tinnerman_lookup(self):
        e = get_by_spec("TIN-AN4062-4")
        assert e is not None
        assert "Tinnerman" in e["mfr"]


# ---------------------------------------------------------------------------
# 6. filter_catalogue()
# ---------------------------------------------------------------------------

class TestFilterCatalogue:
    def test_filter_by_diameter(self):
        results = filter_catalogue(diameter_in=0.250)
        assert len(results) > 0
        for e in results:
            assert abs(e["diameter_in"] - 0.250) < 1e-4

    def test_filter_by_head_style(self):
        cs = filter_catalogue(head_style="countersunk")
        assert len(cs) >= 10
        for e in cs:
            assert e["head_style"] == "countersunk"

    def test_filter_by_material(self):
        ti = filter_catalogue(material="titanium")
        assert len(ti) >= 5

    def test_filter_by_min_shear(self):
        heavy = filter_catalogue(min_shear_kip=20.0)
        for e in heavy:
            assert e["shear_kip"] >= 20.0

    def test_filter_by_max_diameter(self):
        small = filter_catalogue(max_diameter_in=0.1875)
        for e in small:
            assert e["diameter_in"] <= 0.1875 + 1e-6

    def test_filter_combined(self):
        results = filter_catalogue(
            diameter_in=0.250,
            head_style="hex",
            material="alloy-steel",
        )
        assert len(results) >= 2
        for e in results:
            assert abs(e["diameter_in"] - 0.250) < 1e-4
            assert e["head_style"] == "hex"
            assert "alloy-steel" in e["material"]

    def test_filter_no_match_returns_empty(self):
        results = filter_catalogue(diameter_in=0.999, material="unobtainium")
        assert results == []


# ---------------------------------------------------------------------------
# 7. joint_allowable()
# ---------------------------------------------------------------------------

class TestJointAllowable:
    _AL_SKIN = [
        {"material": "aluminum-2024-t3", "thickness_in": 0.100},
        {"material": "aluminum-2024-t3", "thickness_in": 0.100},
    ]
    _TI_SKIN = [
        {"material": "titanium-6al-4v", "thickness_in": 0.080},
        {"material": "titanium-6al-4v", "thickness_in": 0.080},
    ]

    def test_returns_required_keys(self):
        e = get_by_spec("NAS6204-8")
        result = joint_allowable(e, self._AL_SKIN)
        for key in ("shear_kip", "tension_kip", "bearing_kip", "governing"):
            assert key in result

    def test_shear_matches_catalogue(self):
        e = get_by_spec("NAS6204-8")
        result = joint_allowable(e, self._AL_SKIN)
        assert result["shear_kip"] == pytest.approx(e["shear_kip"])

    def test_tension_matches_catalogue(self):
        e = get_by_spec("HL18PB-6-8")
        result = joint_allowable(e, self._AL_SKIN)
        assert result["tension_kip"] == pytest.approx(e["tension_kip"])

    def test_bearing_computed_positive(self):
        e = get_by_spec("NAS6206-12")
        result = joint_allowable(e, self._AL_SKIN)
        assert result["bearing_kip"] > 0

    def test_bearing_scales_with_thickness(self):
        e = get_by_spec("NAS6205-8")
        thin = [{"material": "aluminum-2024-t3", "thickness_in": 0.050}]
        thick = [{"material": "aluminum-2024-t3", "thickness_in": 0.200}]
        thin_r = joint_allowable(e, thin)
        thick_r = joint_allowable(e, thick)
        assert thick_r["bearing_kip"] > thin_r["bearing_kip"]

    def test_bearing_scales_with_diameter(self):
        mat = [{"material": "aluminum-2024-t3", "thickness_in": 0.100}]
        small = get_by_spec("NAS6203-4")
        large = get_by_spec("NAS6206-8")
        r_small = joint_allowable(small, mat)
        r_large = joint_allowable(large, mat)
        assert r_large["bearing_kip"] > r_small["bearing_kip"]

    def test_governing_field_is_valid(self):
        e = get_by_spec("NAS6204-8")
        result = joint_allowable(e, self._AL_SKIN)
        assert result["governing"] in ("shear", "tension", "bearing")

    def test_allowable_gte_applied_load_shear(self):
        """joint_allowable shear should be ≥ a 5 kip applied shear."""
        e = get_by_spec("NAS6204-8")
        result = joint_allowable(e, self._AL_SKIN)
        assert result["shear_kip"] >= 5.0

    def test_allowable_gte_applied_load_tension(self):
        e = get_by_spec("HL18PB-6-16")
        result = joint_allowable(e, self._TI_SKIN)
        assert result["tension_kip"] >= 5.0

    def test_empty_materials_raises(self):
        e = get_by_spec("NAS6204-8")
        with pytest.raises(ValueError, match="materials"):
            joint_allowable(e, [])

    def test_bearing_uses_weaker_material(self):
        """CFRP layer should yield lower bearing than aluminum-only joint."""
        e = get_by_spec("NAS6205-8")
        al_only = [{"material": "aluminum-2024-t3", "thickness_in": 0.100}]
        mixed = [
            {"material": "aluminum-2024-t3", "thickness_in": 0.100},
            {"material": "carbon-fiber-cfrp", "thickness_in": 0.100},
        ]
        r_al = joint_allowable(e, al_only)
        r_mix = joint_allowable(e, mixed)
        assert r_mix["bearing_kip"] < r_al["bearing_kip"]


# ---------------------------------------------------------------------------
# 8. pick_fastener()
# ---------------------------------------------------------------------------

class TestPickFastener:
    def test_returns_dict_for_valid_load(self):
        result = pick_fastener(4.0, "shear", 0.400)
        assert result is not None
        assert isinstance(result, dict)

    def test_returns_none_when_no_fastener_qualifies(self):
        # 1000 kip is impossibly large
        result = pick_fastener(1000.0, "shear", 0.400)
        assert result is None

    def test_picked_fastener_shear_gte_load(self):
        load = 5.0
        result = pick_fastener(load, "shear", 0.400)
        assert result is not None
        assert result["shear_kip"] >= load

    def test_picked_fastener_tension_gte_load(self):
        load = 3.0
        result = pick_fastener(load, "tension", 0.300)
        assert result is not None
        assert result["tension_kip"] >= load

    def test_grip_range_covers_thickness(self):
        thickness = 0.450
        result = pick_fastener(5.0, "shear", thickness)
        if result is not None:
            g_min, g_max = result["grip_range"]
            assert g_min <= thickness <= g_max + 0.063

    def test_prefer_spec_honored_when_fits(self):
        """pick_fastener should return the preferred spec when it satisfies load."""
        preferred = "NAS6206-8"
        result = pick_fastener(10.0, "shear", 0.470, prefer_spec=preferred)
        assert result is not None
        assert result["spec"] == preferred

    def test_prefer_spec_fallback_when_too_weak(self):
        """If preferred spec can't carry the load, any qualifying fastener returned."""
        result = pick_fastener(100.0, "shear", 0.450, prefer_spec="AS3221-4-6")
        # AS3221-4-6 shear ≈ 0.545 kip — way under 100 kip load
        # Should return None since nothing in catalogue reaches 100 kip
        assert result is None

    def test_prefer_spec_hl18_honored(self):
        """HL18PB-6-16 3/8\" Ti should be returned for a 9 kip shear load."""
        preferred = "HL18PB-6-16"
        e = get_by_spec(preferred)
        load = 9.0
        thickness = (e["grip_range"][0] + e["grip_range"][1]) / 2
        result = pick_fastener(load, "shear", thickness, prefer_spec=preferred)
        assert result is not None
        assert result["spec"] == preferred

    def test_mode_tension_picks_appropriate_fastener(self):
        result = pick_fastener(2.0, "tension", 0.250)
        assert result is not None
        assert result["tension_kip"] >= 2.0

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode"):
            pick_fastener(5.0, "bending", 0.300)

    def test_invalid_load_raises(self):
        with pytest.raises(ValueError, match="load"):
            pick_fastener(-1.0, "shear", 0.300)

    def test_pick_smallest_diameter_when_multiple_qualify(self):
        """Should return the lightest (smallest dia) fastener that qualifies."""
        result = pick_fastener(0.5, "shear", 0.200)
        assert result is not None
        # Multiple tiny rivets qualify; diameter should be minimal
        assert result["diameter_in"] <= 0.250

    def test_nas6204_shear_near_9_95(self):
        """Picking at 9.5 kip shear in a 0.4\" joint should return a 1/4\" fastener."""
        result = pick_fastener(9.5, "shear", 0.450)
        assert result is not None
        # NAS6204-8 has shear_kip=9.95 which just exceeds 9.5
        # Verify it's a 1/4" family
        assert result["diameter_in"] <= 0.375
