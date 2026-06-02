"""
Tests for kerf_bim.phase_filter — renovation phase management.

Coverage
--------
- default filters: 4 non-empty filter presets
- existing plan: hides new_construction + demolished elements
- demolition plan: shows existing as visible, demolished as ghosts
- new construction plan: shows only new_construction
- composite filter: all phases visible
- apply_phase_filter with 100 elements: O(N) timing (<50 ms)
- validate_phase_consistency catches inconsistencies
- set_element_phase creates and updates manifest entries
- compute_phase_statistics returns zero-padded counts for all phases
- LLM tool: bim_apply_phase_filter round-trip
- LLM tool: bim_get_phase_filters returns 4 presets
- LLM tool: bim_compute_phase_stats
- LLM tool: bim_set_element_phase
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from kerf_bim.phase_filter import (
    ElementPhase,
    PhaseFilter,
    PhaseFilterResult,
    PhaseTag,
    apply_phase_filter,
    compute_phase_statistics,
    get_default_filters,
    set_element_phase,
    validate_phase_consistency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _make_ep(eid: str, primary: str, demolish: str | None = None) -> ElementPhase:
    return ElementPhase(
        element_id=eid,
        primary_phase=PhaseTag(primary),
        demolish_phase=PhaseTag(demolish) if demolish else None,
    )


# ---------------------------------------------------------------------------
# 1. Default filters
# ---------------------------------------------------------------------------

class TestDefaultFilters:
    def test_returns_four_filters(self):
        filters = get_default_filters()
        assert len(filters) == 4

    def test_filter_names(self):
        names = [f.name for f in get_default_filters()]
        assert "Existing Plan" in names
        assert "Demolition Plan" in names
        assert "New Construction Plan" in names
        assert "Composite (All Phases)" in names

    def test_all_filters_have_visible_phases(self):
        for f in get_default_filters():
            assert len(f.visible_phases) >= 1, f"Filter '{f.name}' has no visible_phases"

    def test_demolition_filter_has_demolished_visible(self):
        demo = next(f for f in get_default_filters() if f.name == "Demolition Plan")
        assert demo.demolished_visible is True

    def test_composite_filter_shows_all_phase_tags(self):
        composite = next(f for f in get_default_filters() if "Composite" in f.name)
        for tag in PhaseTag:
            assert tag in composite.visible_phases, f"{tag} missing from Composite filter"


# ---------------------------------------------------------------------------
# 2. Existing Plan: hides new_construction and demolished
# ---------------------------------------------------------------------------

class TestExistingPlanFilter:
    def _existing_filter(self):
        return next(f for f in get_default_filters() if f.name == "Existing Plan")

    def setup_method(self):
        self.flt = self._existing_filter()
        self.elements = [
            _make_ep("wall-1", "existing"),
            _make_ep("wall-2", "new_construction"),
            _make_ep("wall-3", "existing", demolish="demolish"),
            _make_ep("col-1", "future"),
        ]

    def test_existing_visible(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "wall-1" in result.visible_element_ids

    def test_new_construction_hidden(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "wall-2" in result.hidden_element_ids

    def test_future_hidden(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "col-1" in result.hidden_element_ids

    def test_existing_with_demolish_phase_visible_in_existing_plan(self):
        # wall-3 is existing; demolish_phase='demolish' is NOT in Existing Plan's
        # visible_phases set, so it should be shown as fully visible (not ghosted).
        result = apply_phase_filter(self.elements, self.flt)
        assert "wall-3" in result.visible_element_ids

    def test_no_ghosts_in_existing_plan(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert result.demolished_ghost_ids == []


# ---------------------------------------------------------------------------
# 3. Demolition Plan: existing visible, demolished → ghosts
# ---------------------------------------------------------------------------

class TestDemolitionPlanFilter:
    def _demo_filter(self):
        return next(f for f in get_default_filters() if f.name == "Demolition Plan")

    def setup_method(self):
        self.flt = self._demo_filter()
        self.elements = [
            _make_ep("wall-A", "existing"),
            _make_ep("wall-B", "existing", demolish="demolish"),
            _make_ep("new-C", "new_construction"),
        ]

    def test_plain_existing_is_visible(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "wall-A" in result.visible_element_ids

    def test_demolished_element_is_ghost(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "wall-B" in result.demolished_ghost_ids

    def test_new_construction_hidden_in_demolition_plan(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "new-C" in result.hidden_element_ids

    def test_ghost_not_also_visible(self):
        result = apply_phase_filter(self.elements, self.flt)
        assert "wall-B" not in result.visible_element_ids

    def test_total_accounts_for_all_elements(self):
        result = apply_phase_filter(self.elements, self.flt)
        total = (
            len(result.visible_element_ids)
            + len(result.hidden_element_ids)
            + len(result.demolished_ghost_ids)
        )
        assert total == len(self.elements)


# ---------------------------------------------------------------------------
# 4. O(N) performance: 100 elements
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_apply_100_elements_under_50ms(self):
        elements = [
            ElementPhase(
                element_id=f"el-{i}",
                primary_phase=PhaseTag.EXISTING if i % 2 == 0 else PhaseTag.NEW_CONSTRUCTION,
                demolish_phase=PhaseTag.DEMOLISH if i % 5 == 0 else None,
            )
            for i in range(100)
        ]
        demo_filter = next(f for f in get_default_filters() if f.name == "Demolition Plan")

        t0 = time.perf_counter()
        result = apply_phase_filter(elements, demo_filter)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        assert elapsed_ms < 50, f"apply_phase_filter took {elapsed_ms:.1f} ms for 100 elements"
        total = (
            len(result.visible_element_ids)
            + len(result.hidden_element_ids)
            + len(result.demolished_ghost_ids)
        )
        assert total == 100


# ---------------------------------------------------------------------------
# 5. validate_phase_consistency catches inconsistencies
# ---------------------------------------------------------------------------

class TestValidateConsistency:
    def test_no_warnings_for_clean_data(self):
        eps = [
            _make_ep("w1", "existing"),
            _make_ep("w2", "new_construction"),
            _make_ep("w3", "existing", demolish="demolish"),
        ]
        assert validate_phase_consistency(eps) == []

    def test_catches_self_demolition(self):
        eps = [_make_ep("w1", "existing", demolish="existing")]
        warnings = validate_phase_consistency(eps)
        assert any("demolish_phase equals primary_phase" in w for w in warnings)

    def test_catches_primary_phase_demolish(self):
        eps = [_make_ep("w1", "demolish")]
        warnings = validate_phase_consistency(eps)
        assert any("primary_phase='demolish' is ambiguous" in w for w in warnings)

    def test_catches_demolish_phase_existing(self):
        ep = ElementPhase(
            element_id="w1",
            primary_phase=PhaseTag.NEW_CONSTRUCTION,
            demolish_phase=PhaseTag.EXISTING,
        )
        warnings = validate_phase_consistency([ep])
        assert any("demolish_phase='existing' is invalid" in w for w in warnings)

    def test_catches_duplicate_element_id(self):
        eps = [_make_ep("w1", "existing"), _make_ep("w1", "new_construction")]
        warnings = validate_phase_consistency(eps)
        assert any("duplicate element_id" in w for w in warnings)

    def test_flags_future_with_demolish_phase(self):
        ep = ElementPhase(
            element_id="w1",
            primary_phase=PhaseTag.FUTURE,
            demolish_phase=PhaseTag.DEMOLISH,
        )
        warnings = validate_phase_consistency([ep])
        assert any("future" in w.lower() and "demolish" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# 6. set_element_phase creates and updates entries
# ---------------------------------------------------------------------------

class TestSetElementPhase:
    def test_creates_new_entry(self):
        manifest = {}
        ep = set_element_phase("col-1", PhaseTag.NEW_CONSTRUCTION, manifest)
        assert ep.element_id == "col-1"
        assert ep.primary_phase == PhaseTag.NEW_CONSTRUCTION
        assert len(manifest["element_phases"]) == 1

    def test_updates_existing_entry(self):
        manifest = {}
        set_element_phase("col-1", PhaseTag.EXISTING, manifest)
        ep2 = set_element_phase("col-1", PhaseTag.NEW_CONSTRUCTION, manifest)
        assert ep2.primary_phase == PhaseTag.NEW_CONSTRUCTION
        # Still only one entry
        assert len(manifest["element_phases"]) == 1

    def test_sets_demolish_phase(self):
        manifest = {}
        ep = set_element_phase(
            "w1", PhaseTag.EXISTING, manifest, demolish_phase=PhaseTag.DEMOLISH
        )
        assert ep.demolish_phase == PhaseTag.DEMOLISH

    def test_manifest_serialises_to_json(self):
        manifest = {}
        set_element_phase("w1", PhaseTag.EXISTING, manifest, notes="test note")
        json_str = json.dumps(manifest)
        recovered = json.loads(json_str)
        assert recovered["element_phases"][0]["element_id"] == "w1"
        assert recovered["element_phases"][0]["notes"] == "test note"


# ---------------------------------------------------------------------------
# 7. compute_phase_statistics
# ---------------------------------------------------------------------------

class TestComputePhaseStatistics:
    def test_all_tags_present_in_output(self):
        eps = [_make_ep("w1", "existing"), _make_ep("w2", "new_construction")]
        counts = compute_phase_statistics(eps)
        for tag in PhaseTag:
            assert tag in counts

    def test_counts_are_correct(self):
        eps = [
            _make_ep("w1", "existing"),
            _make_ep("w2", "existing"),
            _make_ep("w3", "new_construction"),
        ]
        counts = compute_phase_statistics(eps)
        assert counts[PhaseTag.EXISTING] == 2
        assert counts[PhaseTag.NEW_CONSTRUCTION] == 1
        assert counts[PhaseTag.FUTURE] == 0

    def test_empty_input(self):
        counts = compute_phase_statistics([])
        assert all(v == 0 for v in counts.values())


# ---------------------------------------------------------------------------
# 8. LLM tool: bim_apply_phase_filter round-trip
# ---------------------------------------------------------------------------

class TestLLMApplyPhaseFilter:
    def _call(self, **kw) -> dict:
        from kerf_bim.tools.phase_filter import run_bim_apply_phase_filter
        return json.loads(_run(run_bim_apply_phase_filter(kw, None)))

    def test_existing_plan_round_trip(self):
        result = self._call(
            element_phases=[
                {"element_id": "w1", "primary_phase": "existing"},
                {"element_id": "w2", "primary_phase": "new_construction"},
            ],
            filter_name="Existing Plan",
        )
        assert result["ok"] is True
        assert "w1" in result["visible_element_ids"]
        assert "w2" in result["hidden_element_ids"]

    def test_demolition_plan_ghosts(self):
        result = self._call(
            element_phases=[
                {"element_id": "w1", "primary_phase": "existing", "demolish_phase": "demolish"},
            ],
            filter_name="Demolition Plan",
        )
        assert result["ok"] is True
        assert "w1" in result["demolished_ghost_ids"]

    def test_unknown_filter_name_returns_error(self):
        result = self._call(
            element_phases=[{"element_id": "w1", "primary_phase": "existing"}],
            filter_name="No Such Filter",
        )
        assert "error" in result

    def test_custom_filter(self):
        result = self._call(
            element_phases=[
                {"element_id": "w1", "primary_phase": "alternate_a"},
                {"element_id": "w2", "primary_phase": "existing"},
            ],
            visible_phases=["alternate_a"],
        )
        assert result["ok"] is True
        assert "w1" in result["visible_element_ids"]
        assert "w2" in result["hidden_element_ids"]


# ---------------------------------------------------------------------------
# 9. LLM tool: bim_get_phase_filters
# ---------------------------------------------------------------------------

class TestLLMGetPhaseFilters:
    def _call(self) -> dict:
        from kerf_bim.tools.phase_filter import run_bim_get_phase_filters
        return json.loads(_run(run_bim_get_phase_filters({}, None)))

    def test_returns_ok(self):
        result = self._call()
        assert result["ok"] is True

    def test_returns_four_filters(self):
        result = self._call()
        assert len(result["filters"]) == 4

    def test_filter_has_required_keys(self):
        result = self._call()
        for f in result["filters"]:
            assert "name" in f
            assert "visible_phases" in f
            assert "demolished_visible" in f
            assert "future_visible" in f


# ---------------------------------------------------------------------------
# 10. LLM tool: bim_compute_phase_stats
# ---------------------------------------------------------------------------

class TestLLMComputePhaseStats:
    def _call(self, eps: list) -> dict:
        from kerf_bim.tools.phase_filter import run_bim_compute_phase_stats
        return json.loads(_run(run_bim_compute_phase_stats({"element_phases": eps}, None)))

    def test_basic_count(self):
        result = self._call([
            {"element_id": "w1", "primary_phase": "existing"},
            {"element_id": "w2", "primary_phase": "existing"},
            {"element_id": "w3", "primary_phase": "new_construction"},
        ])
        assert result["ok"] is True
        assert result["counts"]["existing"] == 2
        assert result["counts"]["new_construction"] == 1

    def test_all_phase_keys_present(self):
        result = self._call([{"element_id": "w1", "primary_phase": "existing"}])
        for tag in PhaseTag:
            assert tag.value in result["counts"]


# ---------------------------------------------------------------------------
# 11. LLM tool: bim_set_element_phase
# ---------------------------------------------------------------------------

class TestLLMSetElementPhase:
    def _call(self, **kw) -> dict:
        from kerf_bim.tools.phase_filter import run_bim_set_element_phase
        return json.loads(_run(run_bim_set_element_phase(kw, None)))

    def test_creates_entry(self):
        result = self._call(element_id="col-1", phase="new_construction")
        assert result["ok"] is True
        assert result["primary_phase"] == "new_construction"
        assert result["manifest_phase_count"] == 1

    def test_with_demolish_phase(self):
        result = self._call(
            element_id="col-1",
            phase="existing",
            demolish_phase="demolish",
            notes="Remove for new entrance",
        )
        assert result["ok"] is True
        assert result["demolish_phase"] == "demolish"
        assert result["notes"] == "Remove for new entrance"

    def test_bad_phase_returns_error(self):
        result = self._call(element_id="col-1", phase="nonexistent_phase")
        assert "error" in result
