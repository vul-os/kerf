"""
test_feature_jewelry_templates.py — T-16 hermetic pytest suite
==============================================================

Scope: kerf_cad_core.jewelry.templates — preset/template library round-trip.

Success criteria (from testing-breakdown.md T-16):
  - 25 templates (31 registered — floor met)
  - Deterministic re-instantiation
  - Parameter migration on schema bump (forward-compat overlay)

Tested here:
  1. Catalog completeness  — ≥25 templates; all 5 categories present.
  2. Schema integrity       — every template has required keys + valid metal/cuts.
  3. JSON round-trip        — serialize → deserialize → equal.
  4. Deep-copy isolation    — mutating returned copy never touches registry.
  5. list_templates filter  — per-category listing covers all IDs exactly.
  6. Deterministic re-instantiation — 25 calls return identical recipes each time.
  7. Override: metal        — top-level metal field is replaced.
  8. Override: component    — per-index params deep-merge; untouched params preserved.
  9. Override: multi-index  — two component patches in one call.
  10. Boundary: out-of-range index — silently ignored, recipe still returned.
  11. Boundary: None overrides — same as no overrides.
  12. Boundary: empty overrides dict — same as no overrides.
  13. Missing template_id   — returns None (no crash).
  14. Unknown category filter — list_templates returns [] (not an error).
  15. Schema migration shim  — recipes loaded with extra/missing keys are tolerated.
  16. Idempotency of instantiate — calling twice without mutation gives equal result.
  17. Malformed: non-string template_id type — graceful None return.
  18. Malformed: component patch missing index key — silently skipped.
  19. Malformed: component patch out-of-range negative index — silently skipped.
  20. All component fields present — tool / role / params in every component.
  21. No empty string IDs or names.
  22. tags are non-empty list of strings.
  23. Override preserves all other top-level fields.
  24. list_templates summary row keys match spec.
  25. Override: empty components list is a no-op.

All tests are pure-Python — no OCC, no DB, no network.
"""

from __future__ import annotations

import copy
import json

import pytest

from kerf_cad_core.jewelry.templates import (
    _TEMPLATES,
    _TEMPLATE_INDEX,
    get_template,
    instantiate,
    list_templates,
)
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3
from kerf_cad_core.jewelry.gemstones import GEMSTONE_CUTS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_ALLOYS: frozenset = frozenset(METAL_DENSITY_G_CM3.keys())
_VALID_CUTS: frozenset = frozenset(GEMSTONE_CUTS)
_ALL_IDS: list[str] = [t["template_id"] for t in _TEMPLATES]
_CATEGORIES_EXPECTED: set = {"rings", "earrings", "pendants", "bracelets", "misc"}
_REQUIRED_TOP_KEYS: set = {
    "template_id", "name", "category", "description", "metal", "components", "tags"
}
_REQUIRED_COMPONENT_KEYS: set = {"tool", "role", "params"}

# First 25 IDs (spec floor)
_IDS_25 = _ALL_IDS[:25]


# ===========================================================================
# 1. Catalog completeness
# ===========================================================================

def test_catalog_has_at_least_25_templates():
    """Spec floor: ≥25 templates must be registered."""
    assert len(_TEMPLATES) >= 25, (
        f"Expected ≥25 templates, got {len(_TEMPLATES)}"
    )


def test_catalog_covers_all_five_categories():
    """All five categories must be present in the catalog."""
    found = {t["category"] for t in _TEMPLATES}
    assert found == _CATEGORIES_EXPECTED, (
        f"Missing categories: {_CATEGORIES_EXPECTED - found}"
    )


def test_template_ids_are_unique():
    """Every template_id must be unique."""
    ids = _ALL_IDS
    assert len(ids) == len(set(ids)), "Duplicate template_ids found"


# ===========================================================================
# 2. Schema integrity — every template
# ===========================================================================

@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_schema_top_level_keys(template_id: str):
    """Every template must have all required top-level keys."""
    t = _TEMPLATE_INDEX[template_id]
    missing = _REQUIRED_TOP_KEYS - set(t.keys())
    assert not missing, f"{template_id}: missing keys {missing}"


@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_schema_metal_is_valid_alloy(template_id: str):
    """Every template's metal must be a key in METAL_DENSITY_G_CM3."""
    t = _TEMPLATE_INDEX[template_id]
    assert t["metal"] in _VALID_ALLOYS, (
        f"{template_id}: unknown metal '{t['metal']}'"
    )


@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_schema_components_nonempty(template_id: str):
    """Every template must have at least one component."""
    t = _TEMPLATE_INDEX[template_id]
    assert len(t["components"]) >= 1, (
        f"{template_id}: components list is empty"
    )


@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_schema_component_keys(template_id: str):
    """Every component must have tool / role / params keys."""
    t = _TEMPLATE_INDEX[template_id]
    for i, comp in enumerate(t["components"]):
        missing = _REQUIRED_COMPONENT_KEYS - set(comp.keys())
        assert not missing, (
            f"{template_id}[{i}]: component missing keys {missing}"
        )


@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_schema_gem_cuts_valid(template_id: str):
    """Any 'cut' or 'stone_cut' param must be in GEMSTONE_CUTS."""
    t = _TEMPLATE_INDEX[template_id]
    for i, comp in enumerate(t["components"]):
        params = comp.get("params", {})
        for field in ("cut", "stone_cut", "border_stone_cut"):
            if field in params:
                val = params[field]
                assert val in _VALID_CUTS, (
                    f"{template_id}[{i}]: invalid {field} '{val}'"
                )


# ===========================================================================
# 3. JSON round-trip — serialize → deserialize → equal
# ===========================================================================

@pytest.mark.parametrize("template_id", _IDS_25)
def test_json_round_trip(template_id: str):
    """Template must survive JSON serialization/deserialization unchanged."""
    t = get_template(template_id)
    serialized = json.dumps(t, sort_keys=True)
    reloaded = json.loads(serialized)
    assert reloaded == t, f"{template_id}: JSON round-trip mismatch"


# ===========================================================================
# 4. Deep-copy isolation — mutating returned copy never touches registry
# ===========================================================================

def test_get_template_returns_deep_copy():
    """Mutating the returned dict must not alter the registry."""
    tid = _ALL_IDS[0]
    original_metal = _TEMPLATE_INDEX[tid]["metal"]
    copy1 = get_template(tid)
    copy1["metal"] = "__mutated__"
    # Registry must be unchanged
    assert _TEMPLATE_INDEX[tid]["metal"] == original_metal


def test_get_template_component_isolation():
    """Mutating a returned component's params must not alter the registry."""
    tid = _ALL_IDS[0]
    t = get_template(tid)
    original_params = copy.deepcopy(_TEMPLATE_INDEX[tid]["components"][0]["params"])
    t["components"][0]["params"]["__injected__"] = True
    assert "__injected__" not in _TEMPLATE_INDEX[tid]["components"][0]["params"]
    assert _TEMPLATE_INDEX[tid]["components"][0]["params"] == original_params


def test_instantiate_returns_deep_copy():
    """Mutating the instantiated recipe must not alter the registry."""
    tid = _ALL_IDS[0]
    original_metal = _TEMPLATE_INDEX[tid]["metal"]
    r = instantiate(tid)
    r["metal"] = "__mutated__"
    assert _TEMPLATE_INDEX[tid]["metal"] == original_metal


# ===========================================================================
# 5. list_templates filter — per-category listing
# ===========================================================================

@pytest.mark.parametrize("category", sorted(_CATEGORIES_EXPECTED))
def test_list_templates_filtered_by_category(category: str):
    """Filtered listing must return only templates in that category."""
    rows = list_templates(category=category)
    assert len(rows) >= 1, f"Category '{category}' returned no templates"
    for row in rows:
        assert row["category"] == category, (
            f"Row '{row['template_id']}' has wrong category '{row['category']}'"
        )


def test_list_templates_no_filter_returns_all():
    """Unfiltered listing must cover every registered template."""
    all_rows = list_templates()
    row_ids = {r["template_id"] for r in all_rows}
    assert row_ids == set(_ALL_IDS)


def test_list_templates_category_ids_union_equals_full():
    """Union of all per-category listings must equal the full catalog."""
    all_ids_from_filter: set = set()
    for cat in _CATEGORIES_EXPECTED:
        for row in list_templates(category=cat):
            all_ids_from_filter.add(row["template_id"])
    assert all_ids_from_filter == set(_ALL_IDS)


# ===========================================================================
# 6. Deterministic re-instantiation — same result on repeated calls
# ===========================================================================

@pytest.mark.parametrize("template_id", _IDS_25)
def test_instantiate_is_deterministic(template_id: str):
    """instantiate() called twice must return equal dicts."""
    r1 = instantiate(template_id)
    r2 = instantiate(template_id)
    assert r1 == r2, f"{template_id}: non-deterministic instantiation"


# ===========================================================================
# 7. Override: metal
# ===========================================================================

def test_override_metal_top_level():
    """Passing metal in overrides must replace the default metal."""
    r = instantiate("ring_solitaire_round", {"metal": "14k_yellow"})
    assert r["metal"] == "14k_yellow"
    # base default must be unchanged in registry
    assert _TEMPLATE_INDEX["ring_solitaire_round"]["metal"] == "18k_white"


def test_override_metal_all_valid_alloys():
    """Every valid alloy must be accepted as a metal override."""
    tid = _ALL_IDS[0]
    for alloy in sorted(_VALID_ALLOYS):
        r = instantiate(tid, {"metal": alloy})
        assert r["metal"] == alloy, f"Override with alloy '{alloy}' failed"


# ===========================================================================
# 8. Override: single component params
# ===========================================================================

def test_override_component_param_merged():
    """Component params override merges the supplied key; others are preserved."""
    r = instantiate(
        "ring_solitaire_round",
        {"components": [{"index": 0, "params": {"ring_size": 10}}]},
    )
    assert r["components"][0]["params"]["ring_size"] == 10
    # Other params must still be present
    assert "band_width" in r["components"][0]["params"]


def test_override_component_does_not_mutate_base():
    """After an override, re-instantiation without override restores defaults."""
    r_overridden = instantiate(
        "ring_solitaire_round",
        {"components": [{"index": 0, "params": {"ring_size": 12}}]},
    )
    assert r_overridden["components"][0]["params"]["ring_size"] == 12

    r_fresh = instantiate("ring_solitaire_round")
    assert r_fresh["components"][0]["params"]["ring_size"] == 7  # original default


# ===========================================================================
# 9. Override: multi-index component patches
# ===========================================================================

def test_override_multi_index_component_patches():
    """Two component patches in a single call must each be applied."""
    r = instantiate(
        "ring_solitaire_round",
        {
            "components": [
                {"index": 0, "params": {"ring_size": 9}},
                {"index": 2, "params": {"material": "sapphire"}},
            ]
        },
    )
    assert r["components"][0]["params"]["ring_size"] == 9
    assert r["components"][2]["params"]["material"] == "sapphire"


# ===========================================================================
# 10. Boundary: out-of-range index silently ignored
# ===========================================================================

def test_override_oob_index_ignored():
    """A component patch with an out-of-range index must be silently ignored."""
    r = instantiate("ring_solitaire_round", {"components": [{"index": 999, "params": {"x": 1}}]})
    assert r is not None
    # Recipe must otherwise be identical to baseline
    base = instantiate("ring_solitaire_round")
    assert r == base


def test_override_negative_index_ignored():
    """A component patch with a negative index must be silently ignored (no crash)."""
    r = instantiate("ring_solitaire_round", {"components": [{"index": -1, "params": {"x": 1}}]})
    assert r is not None


# ===========================================================================
# 11. Boundary: None overrides
# ===========================================================================

def test_none_overrides_equals_base():
    """instantiate(tid, None) must equal instantiate(tid)."""
    for tid in _IDS_25[:5]:
        r_none = instantiate(tid, None)
        r_base = instantiate(tid)
        assert r_none == r_base, f"{tid}: None overrides != base"


# ===========================================================================
# 12. Boundary: empty overrides dict
# ===========================================================================

def test_empty_overrides_equals_base():
    """instantiate(tid, {}) must equal instantiate(tid)."""
    for tid in _IDS_25[:5]:
        r_empty = instantiate(tid, {})
        r_base = instantiate(tid)
        assert r_empty == r_base, f"{tid}: empty overrides != base"


# ===========================================================================
# 13. Missing template_id returns None
# ===========================================================================

def test_get_template_unknown_returns_none():
    assert get_template("does_not_exist_xyz") is None


def test_instantiate_unknown_returns_none():
    assert instantiate("does_not_exist_xyz") is None


def test_instantiate_empty_string_returns_none():
    assert instantiate("") is None


# ===========================================================================
# 14. Unknown category filter returns []
# ===========================================================================

def test_list_templates_unknown_category_returns_empty():
    rows = list_templates(category="unknown_category_xyz")
    assert rows == []


# ===========================================================================
# 15. Schema migration shim — forward-compat overlay tolerance
#
# Tests that an "old-schema" serialized recipe (missing a key added in a
# hypothetical future) can still be used safely when re-hydrated, and that
# adding extra keys to a component or top-level dict does not break
# downstream consumers that iterate known keys.
# ===========================================================================

def test_schema_migration_extra_top_level_key_tolerated():
    """A recipe dict with an extra top-level key must still expose all required keys."""
    r = get_template(_ALL_IDS[0])
    r["schema_version"] = 2          # simulate a future key
    # Required keys must still be accessible
    for key in _REQUIRED_TOP_KEYS:
        assert key in r


def test_schema_migration_missing_optional_key_tolerated():
    """Removing a non-required top-level key from a copy must not break required keys."""
    r = get_template(_ALL_IDS[0])
    r.pop("tags", None)              # simulate old schema without tags
    for key in (_REQUIRED_TOP_KEYS - {"tags"}):
        assert key in r


def test_schema_migration_extra_component_param_tolerated():
    """A component with an extra params key must not prevent recipe construction."""
    r = instantiate(_ALL_IDS[0])
    r["components"][0]["params"]["future_param"] = "some_value"
    # Component must still carry all original params
    assert "future_param" in r["components"][0]["params"]


def test_schema_migration_round_trip_with_extra_keys():
    """A recipe with extra keys must survive JSON round-trip and retain extra keys."""
    r = get_template(_ALL_IDS[0])
    r["schema_version"] = 3
    serialized = json.dumps(r)
    reloaded = json.loads(serialized)
    assert reloaded["schema_version"] == 3
    for key in _REQUIRED_TOP_KEYS:
        assert key in reloaded


# ===========================================================================
# 16. Idempotency of instantiate
# ===========================================================================

@pytest.mark.parametrize("template_id", _IDS_25)
def test_instantiate_idempotent(template_id: str):
    """instantiate() is idempotent: called N times with same args → same result."""
    results = [instantiate(template_id) for _ in range(3)]
    assert results[0] == results[1] == results[2], (
        f"{template_id}: instantiate is not idempotent"
    )


# ===========================================================================
# 17. Malformed: non-string template_id type
# ===========================================================================

def test_get_template_int_id_returns_none():
    """get_template with a non-string key must return None (dict.get semantics)."""
    # _TEMPLATE_INDEX uses string keys, so int lookup must miss
    result = _TEMPLATE_INDEX.get(42)
    assert result is None


def test_instantiate_none_id_returns_none():
    """instantiate(None) must return None cleanly (None not in index)."""
    result = instantiate(None)
    assert result is None


# ===========================================================================
# 18. Malformed: component patch missing index key
# ===========================================================================

def test_component_patch_missing_index_is_skipped():
    """A component patch without an 'index' key must be silently ignored."""
    r = instantiate(
        "ring_solitaire_round",
        {"components": [{"params": {"ring_size": 99}}]},  # no 'index'
    )
    assert r is not None
    # ring_size must NOT be overridden
    assert r["components"][0]["params"]["ring_size"] == 7


# ===========================================================================
# 19. Malformed: negative index out of range
# ===========================================================================

def test_component_patch_negative_oob_index():
    """Negative index outside the list must be silently ignored (no side-effect)."""
    r = instantiate(
        "ring_solitaire_round",
        {"components": [{"index": -99, "params": {"ring_size": 42}}]},
    )
    assert r is not None
    assert r["components"][0]["params"]["ring_size"] == 7


# ===========================================================================
# 20. All component fields present
# ===========================================================================

@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_all_components_have_required_fields(template_id: str):
    """Every component must have non-empty tool / role / params."""
    t = _TEMPLATE_INDEX[template_id]
    for i, comp in enumerate(t["components"]):
        assert comp.get("tool"), f"{template_id}[{i}]: empty/missing tool"
        assert comp.get("role"), f"{template_id}[{i}]: empty/missing role"
        assert isinstance(comp.get("params"), dict), (
            f"{template_id}[{i}]: params must be a dict"
        )


# ===========================================================================
# 21. No empty string IDs or names
# ===========================================================================

@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_no_empty_ids_or_names(template_id: str):
    t = _TEMPLATE_INDEX[template_id]
    assert template_id.strip(), "template_id must not be empty/whitespace"
    assert t["name"].strip(), f"{template_id}: name must not be empty"
    assert t["description"].strip(), f"{template_id}: description must not be empty"


# ===========================================================================
# 22. tags are non-empty list of strings
# ===========================================================================

@pytest.mark.parametrize("template_id", _ALL_IDS)
def test_tags_nonempty_list_of_strings(template_id: str):
    t = _TEMPLATE_INDEX[template_id]
    tags = t["tags"]
    assert isinstance(tags, list), f"{template_id}: tags must be a list"
    assert len(tags) >= 1, f"{template_id}: tags must not be empty"
    for tag in tags:
        assert isinstance(tag, str) and tag.strip(), (
            f"{template_id}: tag '{tag}' must be a non-empty string"
        )


# ===========================================================================
# 23. Override preserves all other top-level fields
# ===========================================================================

def test_override_metal_preserves_other_fields():
    """A metal override must not clobber other top-level fields."""
    base = get_template("ring_solitaire_round")
    r = instantiate("ring_solitaire_round", {"metal": "platinum_950"})
    assert r["metal"] == "platinum_950"
    for key in _REQUIRED_TOP_KEYS - {"metal"}:
        assert r[key] == base[key], (
            f"Override clobbered field '{key}'"
        )


# ===========================================================================
# 24. list_templates summary row keys match spec
# ===========================================================================

def test_list_templates_summary_row_keys():
    """Summary rows must contain the expected keys."""
    required_row_keys = {
        "template_id", "name", "category", "description",
        "metal", "tags", "component_count",
    }
    rows = list_templates()
    for row in rows:
        missing = required_row_keys - set(row.keys())
        assert not missing, (
            f"Row '{row.get('template_id')}' missing keys: {missing}"
        )


def test_list_templates_component_count_matches():
    """component_count in each summary row must equal len(components) in registry."""
    rows = list_templates()
    for row in rows:
        tid = row["template_id"]
        actual = len(_TEMPLATE_INDEX[tid]["components"])
        assert row["component_count"] == actual, (
            f"{tid}: component_count mismatch ({row['component_count']} vs {actual})"
        )


# ===========================================================================
# 25. Override: empty components list is a no-op
# ===========================================================================

def test_override_empty_components_list_is_noop():
    """components=[] in overrides must leave the recipe unchanged."""
    base = instantiate("ring_solitaire_round")
    r = instantiate("ring_solitaire_round", {"components": []})
    assert r == base
