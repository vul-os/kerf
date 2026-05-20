"""
Tests for kerf-lca — embodied-carbon LCA package.

DoD oracle values (ICE v3, must pass within ±5%):
  steel (general)     → 1.80 kg CO₂-eq/kg
  concrete (general)  → 0.115 kg CO₂-eq/kg  (stored as 0.115)
  aluminium (primary) → 9.16 kg CO₂-eq/kg

Covers:
  1. Materials database loads without error.
  2. lookup_material by key, label, alias, substring (case-insensitive).
  3. ICE v3 oracle values within ±5%.
  4. lca_report single-part calculations.
  5. lca_report multi-part BOM with mixed materials.
  6. Circularity score calculation.
  7. Missing material / missing mass_kg edge cases.
  8. LLM tool (run_lca_report) — synchronous call via asyncio.
"""

import asyncio
import json
import math
import pytest

from kerf_lca.materials import load_database, lookup_material, list_materials
from kerf_lca.report import lca_report
from kerf_lca.tools.lca_report import lca_report_spec, run_lca_report


# ---------------------------------------------------------------------------
# 1. Database loads
# ---------------------------------------------------------------------------

def test_database_loads():
    db = load_database()
    assert isinstance(db, dict)
    assert len(db) >= 50, f"Expected 50+ materials, got {len(db)}"


def test_list_materials_count():
    mats = list_materials()
    assert len(mats) >= 50
    # each item must have an 'id'
    for m in mats:
        assert "id" in m
        assert "embodied_carbon_kg_co2_per_kg" in m


# ---------------------------------------------------------------------------
# 2. lookup_material
# ---------------------------------------------------------------------------

def test_lookup_by_key():
    mat = lookup_material("steel_general")
    assert mat is not None
    assert mat["id"] == "steel_general"


def test_lookup_by_alias():
    mat = lookup_material("steel")
    assert mat is not None
    assert mat["id"] == "steel_general"


def test_lookup_case_insensitive():
    mat = lookup_material("ALUMINIUM")
    assert mat is not None
    assert "aluminium" in mat["id"]


def test_lookup_by_label():
    mat = lookup_material("Steel (general, virgin)")
    assert mat is not None
    assert mat["id"] == "steel_general"


def test_lookup_by_alias_concrete():
    mat = lookup_material("concrete")
    assert mat is not None
    assert mat["id"] == "concrete_general"


def test_lookup_missing_returns_none():
    mat = lookup_material("unobtainium_xqz")
    assert mat is None


def test_lookup_empty_returns_none():
    mat = lookup_material("")
    assert mat is None


# ---------------------------------------------------------------------------
# 3. ICE v3 oracle values ±5%
# ---------------------------------------------------------------------------

ORACLE = {
    "steel_general": 1.80,
    "concrete_general": 0.115,
    "aluminium_primary": 9.16,
}


@pytest.mark.parametrize("material_id,expected_factor", ORACLE.items())
def test_ice_v3_oracle_within_5pct(material_id, expected_factor):
    mat = lookup_material(material_id)
    assert mat is not None, f"Material '{material_id}' not found in database"
    actual = mat["embodied_carbon_kg_co2_per_kg"]
    delta = abs(actual - expected_factor) / expected_factor
    assert delta <= 0.05, (
        f"{material_id}: expected {expected_factor}, got {actual} "
        f"(deviation {delta:.1%} > 5%)"
    )


# ---------------------------------------------------------------------------
# 4. lca_report single part
# ---------------------------------------------------------------------------

def test_single_part_steel():
    parts = [{"name": "Bracket", "material": "steel", "mass_kg": 2.0, "quantity": 1}]
    result = lca_report(parts)
    # 2.0 kg × 1.80 kg CO₂-eq/kg = 3.60
    assert math.isclose(result.total_carbon_kg_co2, 3.60, rel_tol=0.05)
    assert len(result.parts) == 1
    assert result.parts[0].material_id == "steel_general"


def test_single_part_aluminium():
    parts = [{"name": "Housing", "material": "aluminium", "mass_kg": 0.5, "quantity": 4}]
    result = lca_report(parts)
    # 0.5 kg × 4 × 9.16 = 18.32
    expected = 0.5 * 4 * 9.16
    assert math.isclose(result.total_carbon_kg_co2, expected, rel_tol=0.05)


def test_single_part_concrete():
    parts = [{"name": "Footing", "material": "concrete", "mass_kg": 500.0, "quantity": 1}]
    result = lca_report(parts)
    # 500 × 0.115 = 57.5
    expected = 500.0 * 0.115
    assert math.isclose(result.total_carbon_kg_co2, expected, rel_tol=0.05)


# ---------------------------------------------------------------------------
# 5. Multi-part BOM
# ---------------------------------------------------------------------------

def test_multi_part_bom():
    parts = [
        {"name": "Frame",    "material": "steel",     "mass_kg": 10.0, "quantity": 1},
        {"name": "Panel",    "material": "glass",     "mass_kg": 2.5,  "quantity": 4},
        {"name": "Fastener", "material": "stainless", "mass_kg": 0.01, "quantity": 50},
    ]
    result = lca_report(parts)
    assert result.total_carbon_kg_co2 > 0

    # check by_material keys present
    assert "steel_general" in result.by_material
    assert "glass_flat" in result.by_material
    assert "steel_stainless" in result.by_material

    # sum of by_material totals == grand total
    mat_sum = sum(v["total_carbon_kg_co2"] for v in result.by_material.values())
    assert math.isclose(mat_sum, result.total_carbon_kg_co2, rel_tol=1e-6)


def test_quantity_multiplier():
    """Two parts identical except quantity — carbon should double."""
    one = lca_report([{"name": "A", "material": "steel", "mass_kg": 1.0, "quantity": 1}])
    two = lca_report([{"name": "A", "material": "steel", "mass_kg": 1.0, "quantity": 2}])
    assert math.isclose(two.total_carbon_kg_co2, 2 * one.total_carbon_kg_co2, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 6. Circularity score
# ---------------------------------------------------------------------------

def test_circularity_score_range():
    parts = [
        {"name": "A", "material": "recycled steel", "mass_kg": 1.0, "quantity": 1},
        {"name": "B", "material": "timber",         "mass_kg": 1.0, "quantity": 1},
    ]
    result = lca_report(parts)
    assert 0 <= result.circularity_score <= 100


def test_circularity_score_high_recycled():
    """100% recycled aluminium has recycled_content=100% → circularity >= 50."""
    parts = [{"name": "Ingot", "material": "recycled aluminium", "mass_kg": 1.0, "quantity": 1}]
    result = lca_report(parts)
    assert result.circularity_score >= 50


def test_circularity_score_low_virgin():
    """Primary aluminium has recycled_content=0% → circularity < 60."""
    parts = [{"name": "Ingot", "material": "aluminium", "mass_kg": 1.0, "quantity": 1}]
    result = lca_report(parts)
    # recyclability is 95% but recycled content is 0%: score = 0.5*0 + 0.5*95 = 47.5
    assert result.circularity_score < 60


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

def test_missing_material_is_warned_not_raised():
    parts = [
        {"name": "Mystery", "material": "unobtainium", "mass_kg": 1.0, "quantity": 1},
        {"name": "Steel part", "material": "steel", "mass_kg": 1.0, "quantity": 1},
    ]
    result = lca_report(parts)
    # mystery part excluded; steel part contributes
    assert result.total_carbon_kg_co2 > 0
    assert any("unobtainium" in w for w in result.warnings)
    # the mystery part in parts list has an empty material_id
    mystery = next(p for p in result.parts if p.name == "Mystery")
    assert mystery.material_id == ""
    assert mystery.total_carbon_kg_co2 == 0.0


def test_missing_mass_uses_fallback():
    parts = [{"name": "Widget", "material": "steel"}]
    result = lca_report(parts, fallback_mass_kg=2.0)
    # 2.0 kg × 1.80 = 3.60
    assert math.isclose(result.total_carbon_kg_co2, 3.60, rel_tol=0.05)
    assert any("fallback" in w for w in result.warnings)


def test_empty_parts_returns_zero():
    result = lca_report([])
    assert result.total_carbon_kg_co2 == 0.0
    assert result.circularity_score == 0.0
    assert result.parts == []


def test_no_material_field_warns_and_zero_carbon():
    parts = [{"name": "NoMat", "mass_kg": 1.0, "quantity": 1}]
    result = lca_report(parts)
    assert result.total_carbon_kg_co2 == 0.0
    assert any("NoMat" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 8. to_dict serialisation
# ---------------------------------------------------------------------------

def test_to_dict_is_json_serialisable():
    parts = [
        {"name": "Frame", "material": "steel", "mass_kg": 5.0, "quantity": 1},
        {"name": "Panel", "material": "glass", "mass_kg": 1.0, "quantity": 2},
    ]
    result = lca_report(parts)
    d = result.to_dict()
    # should not raise
    s = json.dumps(d)
    back = json.loads(s)
    assert back["total_carbon_kg_co2"] > 0
    assert "by_material" in back
    assert "parts" in back
    assert "circularity_score" in back


# ---------------------------------------------------------------------------
# 9. LLM tool (run_lca_report) via asyncio
# ---------------------------------------------------------------------------

class _FakeCtx:
    pool = None
    project_id = None
    user_id = None
    storage = None
    http_client = None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_tool_spec_has_required_fields():
    assert lca_report_spec.name == "lca_report"
    assert "embodied" in lca_report_spec.description.lower()
    assert lca_report_spec.input_schema["type"] == "object"


def test_tool_with_explicit_parts():
    args = json.dumps({
        "parts": [
            {"name": "Beam", "material": "steel", "mass_kg": 10.0, "quantity": 2},
        ]
    }).encode()
    raw = _run(run_lca_report(_FakeCtx(), args))
    d = json.loads(raw)
    assert "error" not in d
    # 10 × 2 × 1.80 = 36.0
    assert math.isclose(d["total_carbon_kg_co2"], 36.0, rel_tol=0.05)
    assert "steel_general" in d["by_material"]


def test_tool_empty_parts_override():
    args = json.dumps({"parts": []}).encode()
    raw = _run(run_lca_report(_FakeCtx(), args))
    d = json.loads(raw)
    # empty list is valid — returns zero carbon (no error)
    assert "error" not in d
    assert d["total_carbon_kg_co2"] == 0.0


def test_tool_no_pool_no_parts_returns_error():
    """When no explicit parts and pool=None, tool should return EMPTY_BOM error."""
    args = json.dumps({}).encode()
    raw = _run(run_lca_report(_FakeCtx(), args))
    d = json.loads(raw)
    assert "error" in d
    assert d.get("code") == "EMPTY_BOM"


def test_tool_bad_args():
    raw = _run(run_lca_report(_FakeCtx(), b"not-json"))
    d = json.loads(raw)
    assert d.get("code") == "BAD_ARGS"


def test_tool_parts_not_array():
    args = json.dumps({"parts": "string"}).encode()
    raw = _run(run_lca_report(_FakeCtx(), args))
    d = json.loads(raw)
    assert d.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 10. Additional material lookups (coverage breadth)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias,expected_id", [
    ("timber",        "timber_softwood"),
    ("glass",         "glass_flat"),
    ("pvc",           "pvc"),
    ("abs",           "abs"),
    ("nylon",         "nylon"),
    ("carbon fibre",  "carbon_fibre"),
    ("copper",        "copper"),
    ("titanium",      "titanium"),
    ("recycled steel","steel_recycled"),
    ("plywood",       "plywood"),
    ("paper",         "paper_kraft"),
    ("rubber",        "rubber_natural"),
])
def test_alias_lookup(alias, expected_id):
    mat = lookup_material(alias)
    assert mat is not None, f"'{alias}' not found"
    assert mat["id"] == expected_id, f"'{alias}' → {mat['id']}, expected {expected_id}"
