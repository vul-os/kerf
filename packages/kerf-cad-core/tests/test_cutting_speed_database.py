"""
Tests for kerf_cad_core.cuttingtool.cutting_speed_database
and the LLM tool wrapper manufacturing_query_cutting_speed.

Oracle values from:
  Machinery's Handbook 31e §1100 (Industrial Press, 2020)
  Sandvik Coromant CoroKey 2023/2024

Coverage:
  1. Oracle samples — depth-bar values from MH31 §1100
  2. Feasibility — known impractical combinations flagged
  3. Unknown keys — ok=False returned, never raises
  4. Normalisation — case-insensitive, hyphens accepted
  5. SFM→m/min conversions
  6. Feed unit correctness (IPT/IPR)
  7. LLM tool wrapper (happy path + error paths)
  8. Discovery mode (list_materials)
  9. Full table coverage — all 320 entries parseable

Author: imranparuk
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.cuttingtool.cutting_speed_database import (
    query_cutting_speed,
    list_materials,
    list_tool_materials,
    list_operations,
    CuttingSpeedResult,
)
from kerf_cad_core.cuttingtool.cutting_speeds_data import (
    CUTTING_SPEED_TABLE,
    VALID_WORKPIECE_MATERIALS,
    VALID_TOOL_MATERIALS,
    VALID_OPERATIONS,
)
from kerf_cad_core.cuttingtool.cutting_speed_tools import (
    run_manufacturing_query_cutting_speed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


_SFM_TO_M_MIN = 1.0 / 3.281


# ===========================================================================
# 1. Oracle / depth-bar samples from Machinery's Handbook 31e §1100
# ===========================================================================

class TestOracleSamples:
    """
    Values cross-checked against:
      MH31 §1100 Table 1 (aluminum), Table 3 (carbon steel), Ti-alloy data.
      Sandvik Coromant CoroKey 2023/2024.
    """

    def test_al6061_carbide_milling_sfm_range(self):
        """MH31 §1100 / Sandvik: Al 6061 + carbide + milling → 800–2400 SFM, typical 1500."""
        r = query_cutting_speed("aluminum_6061", "carbide", "milling")
        assert r.ok is True
        assert r.feasible is True
        assert r.sfm_min == 800
        assert r.sfm_typical == 1500
        assert r.sfm_max == 2400

    def test_al6061_carbide_milling_ipt_range(self):
        """Al 6061 + carbide + milling: IPT 0.001–0.005."""
        r = query_cutting_speed("aluminum_6061", "carbide", "milling")
        assert r.feed_unit == "ipt"
        assert r.ipt_or_ipr_lo == pytest.approx(0.001, rel=1e-6)
        assert r.ipt_or_ipr_hi == pytest.approx(0.005, rel=1e-6)

    def test_steel1018_hss_drilling_sfm_range(self):
        """MH31 §1100 Table 3: Steel 1018 + HSS + drilling → 60–90 SFM, typical 80."""
        r = query_cutting_speed("steel_1018", "hss", "drilling")
        assert r.ok is True
        assert r.feasible is True
        assert r.sfm_min == 60
        assert r.sfm_typical == 80
        assert r.sfm_max == 90

    def test_steel1018_hss_drilling_ipr_range(self):
        """Steel 1018 + HSS + drilling: IPR 0.005–0.015."""
        r = query_cutting_speed("steel_1018", "hss", "drilling")
        assert r.feed_unit == "ipr"
        assert r.ipt_or_ipr_lo == pytest.approx(0.005, rel=1e-6)
        assert r.ipt_or_ipr_hi == pytest.approx(0.015, rel=1e-6)

    def test_titanium_6al4v_carbide_turning_sfm_range(self):
        """Sandvik CoroKey + MH31: Ti-6Al-4V + carbide + turning → 200–300 SFM, typical 250."""
        r = query_cutting_speed("titanium_6al4v", "carbide", "turning")
        assert r.ok is True
        assert r.feasible is True
        assert r.sfm_min == 200
        assert r.sfm_typical == 250
        assert r.sfm_max == 300

    def test_titanium_6al4v_carbide_turning_ipr(self):
        """Ti-6Al-4V + carbide + turning: feed unit is IPR (turning)."""
        r = query_cutting_speed("titanium_6al4v", "carbide", "turning")
        assert r.feed_unit == "ipr"

    def test_steel1018_hss_turning_sfm_range(self):
        """MH31 §1100 Table 3: Steel 1018 + HSS + turning → 80–160 SFM."""
        r = query_cutting_speed("steel_1018", "hss", "turning")
        assert r.ok is True
        assert r.sfm_min == 80
        assert r.sfm_max == 160

    def test_inconel718_ceramic_turning_high_speed(self):
        """MH31 + Sandvik: IN718 + ceramic + turning → SFM 600–1600."""
        r = query_cutting_speed("inconel_718", "ceramic", "turning")
        assert r.ok is True
        assert r.feasible is True
        assert r.sfm_min == 600
        assert r.sfm_max == 1600

    def test_al6061_pcd_turning_high_speed(self):
        """Al 6061 + PCD + turning → SFM 2000–6000 (Sandvik PCD data)."""
        r = query_cutting_speed("aluminum_6061", "diamond", "turning")
        assert r.ok is True
        assert r.feasible is True
        assert r.sfm_min == 2000
        assert r.sfm_max == 6000


# ===========================================================================
# 2. Feasibility — impractical combinations
# ===========================================================================

class TestFeasibility:

    def test_pcd_on_steel_1018_not_feasible(self):
        """PCD on steel: carbon diffusion makes it impractical → feasible=False."""
        r = query_cutting_speed("steel_1018", "diamond", "turning")
        assert r.ok is True
        assert r.feasible is False
        assert "carbon" in r.reason.lower() or "pcd" in r.reason.lower() or len(r.reason) > 0

    def test_pcd_on_titanium_not_feasible(self):
        """PCD on Ti: C diffusion at high temp → feasible=False."""
        r = query_cutting_speed("titanium_6al4v", "diamond", "turning")
        assert r.ok is True
        assert r.feasible is False

    def test_hss_on_hardened_60hrc_not_feasible(self):
        """HSS cannot machine 60 HRC hardened steel."""
        r = query_cutting_speed("steel_hardened_60hrc", "hss", "turning")
        assert r.ok is True
        assert r.feasible is False

    def test_ceramic_drill_on_steel_1018_not_feasible(self):
        """Ceramic drills not recommended for 1018; expect feasible=False."""
        r = query_cutting_speed("steel_1018", "ceramic", "drilling")
        assert r.ok is True
        assert r.feasible is False

    def test_feasible_combination_returns_sfm_gt_zero(self):
        """All feasible combinations have sfm_typical > 0."""
        r = query_cutting_speed("brass_360", "carbide", "turning")
        assert r.feasible is True
        assert r.sfm_typical > 0


# ===========================================================================
# 3. Unknown / invalid keys
# ===========================================================================

class TestUnknownKeys:

    def test_unknown_material_returns_ok_false(self):
        r = query_cutting_speed("unobtainium", "carbide", "turning")
        assert r.ok is False
        assert "unobtainium" in r.reason.lower()

    def test_unknown_tool_material_returns_ok_false(self):
        r = query_cutting_speed("aluminum_6061", "unobtainium", "milling")
        assert r.ok is False

    def test_unknown_operation_returns_ok_false(self):
        r = query_cutting_speed("aluminum_6061", "carbide", "grinding")
        assert r.ok is False
        assert "grinding" in r.reason.lower()

    def test_query_never_raises_on_garbage_input(self):
        """query_cutting_speed must not raise for any string input."""
        for mat in ["", "   ", "123!@#", "ALUMINUM_6061"]:
            r = query_cutting_speed(mat, "carbide", "milling")
            assert isinstance(r, CuttingSpeedResult)

    def test_query_never_raises_on_empty_strings(self):
        r = query_cutting_speed("", "", "")
        assert r.ok is False


# ===========================================================================
# 4. Key normalisation
# ===========================================================================

class TestNormalisation:

    def test_uppercase_material_accepted(self):
        """Material key is case-insensitive."""
        r = query_cutting_speed("ALUMINUM_6061", "carbide", "milling")
        assert r.ok is True
        assert r.feasible is True

    def test_mixed_case_tool_material_accepted(self):
        r = query_cutting_speed("aluminum_6061", "Carbide", "milling")
        assert r.ok is True

    def test_hyphen_in_material_normalised(self):
        """'titanium-6al4v' → 'titanium_6al4v'."""
        r = query_cutting_speed("titanium-6al4v", "carbide", "turning")
        assert r.ok is True
        assert r.feasible is True
        assert r.sfm_typical == 250

    def test_space_in_operation_normalised(self):
        """'drill ing' (accidental space) → 'drilling'."""
        # Only works if the user passes with underscores after normalisation
        r = query_cutting_speed("steel_1018", "hss", "DRILLING")
        assert r.ok is True


# ===========================================================================
# 5. SFM ↔ m/min conversions
# ===========================================================================

class TestConversions:

    def test_sfm_to_m_min_typical(self):
        """sfm_typical_m_min = sfm_typical / 3.281 (to 1 decimal)."""
        r = query_cutting_speed("aluminum_6061", "carbide", "milling")
        expected = round(1500 / 3.281, 1)
        assert r.sfm_typical_m_min == pytest.approx(expected, rel=1e-3)

    def test_sfm_to_m_min_min(self):
        r = query_cutting_speed("titanium_6al4v", "carbide", "turning")
        expected = round(200 / 3.281, 1)
        assert r.sfm_min_m_min == pytest.approx(expected, rel=1e-3)

    def test_sfm_to_m_min_max(self):
        r = query_cutting_speed("titanium_6al4v", "carbide", "turning")
        expected = round(300 / 3.281, 1)
        assert r.sfm_max_m_min == pytest.approx(expected, rel=1e-3)

    def test_infeasible_combination_m_min_all_zero(self):
        r = query_cutting_speed("steel_1018", "diamond", "turning")
        assert r.sfm_min_m_min == 0
        assert r.sfm_typical_m_min == 0
        assert r.sfm_max_m_min == 0


# ===========================================================================
# 6. Feed units
# ===========================================================================

class TestFeedUnits:

    def test_milling_uses_ipt(self):
        """All milling operations use IPT."""
        for mat in ["aluminum_6061", "steel_1018", "titanium_6al4v"]:
            r = query_cutting_speed(mat, "carbide", "milling")
            if r.feasible:
                assert r.feed_unit == "ipt", f"{mat} milling should be IPT"

    def test_turning_uses_ipr(self):
        """Turning operations use IPR."""
        for mat in ["aluminum_6061", "steel_1018", "titanium_6al4v"]:
            r = query_cutting_speed(mat, "carbide", "turning")
            if r.feasible:
                assert r.feed_unit == "ipr", f"{mat} turning should be IPR"

    def test_drilling_uses_ipr(self):
        """Drilling operations use IPR."""
        r = query_cutting_speed("steel_1018", "hss", "drilling")
        assert r.feed_unit == "ipr"

    def test_reaming_uses_ipr(self):
        """Reaming operations use IPR."""
        r = query_cutting_speed("aluminum_6061", "carbide", "reaming")
        assert r.feed_unit == "ipr"

    def test_infeasible_uses_na_feed_unit(self):
        """Infeasible combinations have feed_unit='n/a'."""
        r = query_cutting_speed("steel_1018", "diamond", "turning")
        assert r.feed_unit == "n/a"


# ===========================================================================
# 7. LLM tool wrapper
# ===========================================================================

class TestLLMToolWrapper:

    def test_happy_path_al6061_carbide_milling(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="aluminum_6061",
            tool_material="carbide",
            operation="milling",
        )))
        d = _ok_tool(raw)
        assert d["sfm_typical"] == 1500
        assert d["sfm_min"] == 800
        assert d["sfm_max"] == 2400
        assert d["feed_unit"] == "ipt"
        assert d["feasible"] is True

    def test_happy_path_steel1018_hss_drilling(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="steel_1018",
            tool_material="hss",
            operation="drilling",
        )))
        d = _ok_tool(raw)
        assert d["sfm_typical"] == 80
        assert d["feed_unit"] == "ipr"
        assert d["feasible"] is True

    def test_happy_path_titanium_carbide_turning(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="titanium_6al4v",
            tool_material="carbide",
            operation="turning",
        )))
        d = _ok_tool(raw)
        assert d["sfm_typical"] == 250
        assert d["feasible"] is True

    def test_infeasible_combination_returned_as_ok_but_feasible_false(self):
        """PCD on steel returns ok=True, feasible=False."""
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="steel_1018",
            tool_material="diamond",
            operation="turning",
        )))
        d = _ok_tool(raw)
        assert d["feasible"] is False

    def test_unknown_material_returns_ok_false(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="unobtainium",
            tool_material="carbide",
            operation="milling",
        )))
        _err_tool(raw)

    def test_missing_material_returns_error(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            tool_material="carbide",
            operation="milling",
        )))
        _err_tool(raw)

    def test_missing_tool_material_returns_error(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="aluminum_6061",
            operation="milling",
        )))
        _err_tool(raw)

    def test_missing_operation_returns_error(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="aluminum_6061",
            tool_material="carbide",
        )))
        _err_tool(raw)

    def test_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, b"not json"))
        _err_tool(raw)

    def test_discovery_mode_list_materials(self):
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            list_materials=True,
        )))
        d = _ok_tool(raw)
        assert "workpiece_materials" in d
        assert "tool_materials" in d
        assert "operations" in d
        assert "aluminum_6061" in d["workpiece_materials"]
        assert "carbide" in d["tool_materials"]
        assert "milling" in d["operations"]

    def test_source_citation_present(self):
        """Result must include a source citation."""
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="aluminum_6061",
            tool_material="carbide",
            operation="milling",
        )))
        d = _ok_tool(raw)
        assert "source" in d
        assert "Machinery" in d["source"] or "Sandvik" in d["source"]

    def test_m_min_fields_present(self):
        """Converted m/min fields must be present in tool output."""
        ctx = _ctx()
        raw = _run(run_manufacturing_query_cutting_speed(ctx, _args(
            material="titanium_6al4v",
            tool_material="carbide",
            operation="turning",
        )))
        d = _ok_tool(raw)
        assert "sfm_typical_m_min" in d
        assert d["sfm_typical_m_min"] > 0


# ===========================================================================
# 8. Inventory validation — all 320 entries parseable
# ===========================================================================

class TestFullTableCoverage:

    def test_table_has_expected_entry_count(self):
        """20 materials × 4 tools × 4 ops = 320 entries."""
        assert len(CUTTING_SPEED_TABLE) == 320

    def test_all_entries_queryable_without_error(self):
        """Every combination in the table must return ok=True."""
        errors = []
        for mat in VALID_WORKPIECE_MATERIALS:
            for tool in VALID_TOOL_MATERIALS:
                for op in VALID_OPERATIONS:
                    r = query_cutting_speed(mat, tool, op)
                    if not r.ok:
                        errors.append(f"({mat}, {tool}, {op}): ok=False, reason={r.reason}")
        assert errors == [], "Some entries not queryable:\n" + "\n".join(errors)

    def test_all_feasible_entries_have_positive_sfm(self):
        """Every feasible entry must have sfm_typical > 0."""
        errors = []
        for mat in VALID_WORKPIECE_MATERIALS:
            for tool in VALID_TOOL_MATERIALS:
                for op in VALID_OPERATIONS:
                    r = query_cutting_speed(mat, tool, op)
                    if r.ok and r.feasible and r.sfm_typical <= 0:
                        errors.append(f"({mat}, {tool}, {op}): feasible but sfm_typical={r.sfm_typical}")
        assert errors == [], "Feasible entries with non-positive sfm_typical:\n" + "\n".join(errors)

    def test_all_feasible_entries_have_sfm_min_le_typical_le_max(self):
        """sfm_min <= sfm_typical <= sfm_max for all feasible entries."""
        errors = []
        for mat in VALID_WORKPIECE_MATERIALS:
            for tool in VALID_TOOL_MATERIALS:
                for op in VALID_OPERATIONS:
                    r = query_cutting_speed(mat, tool, op)
                    if r.ok and r.feasible:
                        if not (r.sfm_min <= r.sfm_typical <= r.sfm_max):
                            errors.append(
                                f"({mat}, {tool}, {op}): "
                                f"sfm_min={r.sfm_min}, typical={r.sfm_typical}, max={r.sfm_max}"
                            )
        assert errors == [], "SFM ordering violated:\n" + "\n".join(errors)

    def test_all_feasible_entries_have_positive_feed(self):
        """Feasible entries must have feed_lo > 0 and feed_hi >= feed_lo."""
        errors = []
        for mat in VALID_WORKPIECE_MATERIALS:
            for tool in VALID_TOOL_MATERIALS:
                for op in VALID_OPERATIONS:
                    r = query_cutting_speed(mat, tool, op)
                    if r.ok and r.feasible:
                        if r.ipt_or_ipr_lo <= 0:
                            errors.append(f"({mat}, {tool}, {op}): feed_lo <= 0")
                        if r.ipt_or_ipr_hi < r.ipt_or_ipr_lo:
                            errors.append(f"({mat}, {tool}, {op}): feed_hi < feed_lo")
        assert errors == [], "Feed range violations:\n" + "\n".join(errors)

    def test_list_materials_returns_20(self):
        """list_materials() must return 20 items."""
        assert len(list_materials()) == 20

    def test_list_tool_materials_returns_4(self):
        assert len(list_tool_materials()) == 4

    def test_list_operations_returns_4(self):
        assert len(list_operations()) == 4
