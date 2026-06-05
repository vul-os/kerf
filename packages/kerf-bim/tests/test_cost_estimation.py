"""
Tests for kerf_bim.cost_estimation — 5D cost estimation engine.

Coverage
--------
- UnitCostEntry: valid + invalid (bad unit, negative cost)
- UnitCostDB.lookup: exact, trade-match, wildcard
- take_off: area/volume/each/lm extraction from element dicts
- cost_rollup: total, by_phase, by_trade, by_category, unpriced
- default_unit_cost_db: entries exist for all major categories
- LLM tool: bim_5d_quantity_takeoff
- LLM tool: bim_5d_cost_rollup
- LLM tool: bim_5d_cost_summary
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_bim.cost_estimation import (
    UnitCostDB,
    UnitCostEntry,
    QuantityRecord,
    CostRollup,
    take_off,
    cost_rollup,
    default_unit_cost_db,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. UnitCostEntry
# ---------------------------------------------------------------------------

class TestUnitCostEntry:
    def test_valid_entry(self):
        e = UnitCostEntry(category="Wall", unit="m2", unit_cost=250.0)
        assert e.category == "Wall"

    def test_invalid_unit(self):
        with pytest.raises(ValueError, match="unit must be one of"):
            UnitCostEntry(category="Wall", unit="sqft", unit_cost=25.0)

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError, match="unit_cost must be >= 0"):
            UnitCostEntry(category="Wall", unit="m2", unit_cost=-1.0)

    def test_zero_cost_allowed(self):
        e = UnitCostEntry(category="Generic", unit="each", unit_cost=0.0)
        assert e.unit_cost == 0.0


# ---------------------------------------------------------------------------
# 2. UnitCostDB lookup
# ---------------------------------------------------------------------------

class TestUnitCostDBLookup:
    def _db(self):
        return UnitCostDB(entries=[
            UnitCostEntry("Wall", "m2",   200.0, trade="structural"),
            UnitCostEntry("Wall", "m2",   180.0, trade=""),
            UnitCostEntry("Slab", "m2",   300.0, trade="structural", phase="shell"),
            UnitCostEntry("Door", "each", 1200.0),
        ])

    def test_exact_trade_match(self):
        db = self._db()
        e = db.lookup("Wall", trade="structural")
        assert e.unit_cost == 200.0

    def test_wildcard_trade_fallback(self):
        db = self._db()
        e = db.lookup("Wall", trade="architectural")
        # Falls back to wildcard (trade="")
        assert e is not None

    def test_unknown_category_returns_none(self):
        db = self._db()
        assert db.lookup("Roof") is None

    def test_door_found(self):
        db = self._db()
        e = db.lookup("Door")
        assert e.unit_cost == 1200.0

    def test_phase_match(self):
        db = self._db()
        e = db.lookup("Slab", trade="structural", phase="shell")
        assert e.unit_cost == 300.0


# ---------------------------------------------------------------------------
# 3. take_off
# ---------------------------------------------------------------------------

class TestTakeOff:
    def test_wall_area_from_dimensions(self):
        elements = [{"id": "w1", "category": "Wall", "width": 5.0, "height": 3.0}]
        records = take_off(elements)
        assert len(records) == 1
        assert records[0].unit == "m2"
        assert records[0].quantity == pytest.approx(15.0)

    def test_wall_area_from_area_key(self):
        elements = [{"id": "w1", "category": "Wall", "area": 20.0}]
        records = take_off(elements)
        assert records[0].quantity == pytest.approx(20.0)

    def test_column_volume(self):
        elements = [{"id": "c1", "category": "Column", "volume": 0.5}]
        records = take_off(elements)
        assert records[0].unit == "m3"
        assert records[0].quantity == pytest.approx(0.5)

    def test_door_count(self):
        elements = [{"id": "d1", "category": "Door"}]
        records = take_off(elements)
        assert records[0].unit == "each"
        assert records[0].quantity == pytest.approx(1.0)

    def test_railing_length(self):
        elements = [{"id": "r1", "category": "Railing", "length": 12.5}]
        records = take_off(elements)
        assert records[0].unit == "lm"
        assert records[0].quantity == pytest.approx(12.5)

    def test_element_without_id_skipped(self):
        elements = [{"category": "Wall", "area": 10.0}]
        records = take_off(elements)
        assert len(records) == 0

    def test_trade_and_phase_propagated(self):
        elements = [{"id": "e1", "category": "Wall", "area": 5.0, "trade": "structural", "phase": "shell"}]
        records = take_off(elements)
        assert records[0].trade == "structural"
        assert records[0].phase == "shell"

    def test_multiple_elements(self):
        elements = [
            {"id": "w1", "category": "Wall", "area": 10.0},
            {"id": "w2", "category": "Wall", "area": 20.0},
            {"id": "d1", "category": "Door"},
        ]
        records = take_off(elements)
        assert len(records) == 3


# ---------------------------------------------------------------------------
# 4. cost_rollup
# ---------------------------------------------------------------------------

class TestCostRollup:
    def _simple_db(self):
        return UnitCostDB(entries=[
            UnitCostEntry("Wall", "m2",   200.0, trade="structural", phase="shell"),
            UnitCostEntry("Door", "each", 1000.0),
        ])

    def _quantities(self):
        return [
            QuantityRecord("w1", "Wall", 15.0, "m2", trade="structural", phase="shell"),
            QuantityRecord("w2", "Wall", 20.0, "m2", trade="structural", phase="shell"),
            QuantityRecord("d1", "Door",  1.0, "each"),
            QuantityRecord("x1", "Roof",  50.0, "m2"),  # no rate → unpriced
        ]

    def test_total_cost(self):
        rollup = cost_rollup(self._quantities(), self._simple_db())
        expected = (15.0 + 20.0) * 200.0 + 1.0 * 1000.0
        assert rollup.total_cost == pytest.approx(expected)

    def test_by_phase(self):
        rollup = cost_rollup(self._quantities(), self._simple_db())
        assert "(unphased)" in rollup.by_phase or "shell" in rollup.by_phase

    def test_by_trade(self):
        rollup = cost_rollup(self._quantities(), self._simple_db())
        assert "structural" in rollup.by_trade

    def test_by_category(self):
        rollup = cost_rollup(self._quantities(), self._simple_db())
        assert "Wall" in rollup.by_category
        assert "Door" in rollup.by_category

    def test_unpriced_element(self):
        rollup = cost_rollup(self._quantities(), self._simple_db())
        assert len(rollup.unpriced) == 1
        assert rollup.unpriced[0].element_id == "x1"

    def test_empty_quantities(self):
        rollup = cost_rollup([], self._simple_db())
        assert rollup.total_cost == 0.0
        assert rollup.line_items == []


# ---------------------------------------------------------------------------
# 5. default_unit_cost_db
# ---------------------------------------------------------------------------

class TestDefaultUnitCostDB:
    def test_major_categories_present(self):
        db = default_unit_cost_db()
        for cat in ["Wall", "Slab", "Column", "Door", "Window", "Stair", "Railing"]:
            assert db.lookup(cat) is not None, f"{cat} not in default DB"

    def test_usd_currency(self):
        db = default_unit_cost_db("USD")
        e = db.lookup("Wall")
        assert e.currency == "USD"

    def test_custom_currency(self):
        db = default_unit_cost_db("ZAR")
        e = db.lookup("Door")
        assert e.currency == "ZAR"

    def test_all_positive_costs(self):
        db = default_unit_cost_db()
        for e in db.entries:
            assert e.unit_cost > 0


# ---------------------------------------------------------------------------
# 6. LLM tool: bim_5d_quantity_takeoff
# ---------------------------------------------------------------------------

class TestLLMQuantityTakeoff:
    def _call(self, elements) -> dict:
        from kerf_bim.tools.cost_estimation import run_bim_5d_quantity_takeoff
        return json.loads(_run(run_bim_5d_quantity_takeoff({"elements": elements}, None)))

    def test_basic_takeoff(self):
        elements = [
            {"id": "w1", "category": "Wall", "width": 5.0, "height": 3.0},
            {"id": "d1", "category": "Door"},
        ]
        result = self._call(elements)
        assert result["ok"] is True
        assert result["record_count"] == 2

    def test_empty_elements(self):
        result = self._call([])
        assert result["ok"] is True
        assert result["record_count"] == 0

    def test_quantity_fields_present(self):
        elements = [{"id": "c1", "category": "Column", "volume": 0.5}]
        result = self._call(elements)
        q = result["quantities"][0]
        assert q["unit"] == "m3"
        assert q["quantity"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 7. LLM tool: bim_5d_cost_rollup
# ---------------------------------------------------------------------------

class TestLLMCostRollup:
    def _call(self, quantities, unit_costs=None) -> dict:
        from kerf_bim.tools.cost_estimation import run_bim_5d_cost_rollup
        params = {"quantities": quantities}
        if unit_costs:
            params["unit_costs"] = unit_costs
        return json.loads(_run(run_bim_5d_cost_rollup(params, None)))

    def test_basic_rollup_with_builtin_rates(self):
        quantities = [
            {"element_id": "w1", "category": "Wall", "quantity": 10.0, "unit": "m2"},
        ]
        result = self._call(quantities)
        assert result["ok"] is True
        assert result["total_cost"] > 0

    def test_custom_rates(self):
        quantities = [{"element_id": "w1", "category": "Wall", "quantity": 5.0, "unit": "m2"}]
        rates = [{"category": "Wall", "unit": "m2", "unit_cost": 500.0}]
        result = self._call(quantities, rates)
        assert result["total_cost"] == pytest.approx(2500.0)

    def test_unpriced_reported(self):
        quantities = [{"element_id": "u1", "category": "Spacecraft", "quantity": 1.0, "unit": "each"}]
        result = self._call(quantities)
        assert result["unpriced_count"] == 1

    def test_grouping_keys_present(self):
        quantities = [{"element_id": "w1", "category": "Wall", "quantity": 10.0, "unit": "m2", "trade": "structural", "phase": "shell"}]
        result = self._call(quantities)
        assert "by_phase" in result
        assert "by_trade" in result
        assert "by_category" in result


# ---------------------------------------------------------------------------
# 8. LLM tool: bim_5d_cost_summary
# ---------------------------------------------------------------------------

class TestLLMCostSummary:
    def _call(self, elements, unit_costs=None) -> dict:
        from kerf_bim.tools.cost_estimation import run_bim_5d_cost_summary
        params = {"elements": elements}
        if unit_costs:
            params["unit_costs"] = unit_costs
        return json.loads(_run(run_bim_5d_cost_summary(params, None)))

    def test_full_pipeline(self):
        elements = [
            {"id": "w1", "category": "Wall", "area": 20.0, "trade": "architectural", "phase": "shell"},
            {"id": "d1", "category": "Door", "trade": "architectural", "phase": "fit-out"},
            {"id": "c1", "category": "Column", "volume": 0.8, "trade": "structural", "phase": "shell"},
        ]
        result = self._call(elements)
        assert result["ok"] is True
        assert result["element_count"] == 3
        assert result["total_cost"] > 0

    def test_empty_returns_zero(self):
        result = self._call([])
        assert result["ok"] is True
        assert result["total_cost"] == 0.0
