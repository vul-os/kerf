"""
Tests for kerf_electronics.atopile.library — component-library bridge.

Covers:
  - parse_value: SI suffix forms, interleaved-decimal ("4n7"), plain float, plain int
  - MockCatalogue.search: part_type / package / value filtering
  - resolve_component: happy path (returns JLCPCB part from mock fixture)
  - resolve_component: no-match returns {"resolved": False, "warning": ...}
  - resolve_component: missing "part" key returns structured error
  - resolve_component: empty spec returns structured error
  - resolve_many: batch resolution
  - Value tolerance: ±5 % passes; >5 % fails
  - Package mismatch: returns no-match
  - Multiple candidates: best-stock candidate returned first

All tests are hermetic (no network calls).  The module-level
set_catalogue() / MockCatalogue fixture path are used to inject a
controlled catalogue.

Author: imranparuk
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

# Resolve fixture path relative to this test file.
_FIXTURE = Path(__file__).parent / "fixtures" / "atopile" / "jlcpcb_resistors.json"

# Import under test
from kerf_electronics.atopile.library import (
    MockCatalogue,
    parse_value,
    resolve_component,
    resolve_many,
    set_catalogue,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _mock_cat() -> MockCatalogue:
    return MockCatalogue(_FIXTURE)


# ─── 1. parse_value ──────────────────────────────────────────────────────────

class TestParseValue(unittest.TestCase):

    def test_10k(self):
        self.assertAlmostEqual(parse_value("10k"), 10_000.0)

    def test_100k(self):
        self.assertAlmostEqual(parse_value("100k"), 100_000.0)

    def test_1M(self):
        self.assertAlmostEqual(parse_value("1M"), 1_000_000.0)

    def test_470(self):
        self.assertAlmostEqual(parse_value("470"), 470.0)

    def test_100(self):
        self.assertAlmostEqual(parse_value("100"), 100.0)

    def test_4n7_interleaved(self):
        """EIA interleaved-decimal: '4n7' → 4.7e-9"""
        self.assertAlmostEqual(parse_value("4n7"), 4.7e-9, places=20)

    def test_33p(self):
        self.assertAlmostEqual(parse_value("33p"), 33e-12, places=20)

    def test_100n(self):
        self.assertAlmostEqual(parse_value("100n"), 100e-9, places=20)

    def test_4_7_plain_float(self):
        self.assertAlmostEqual(parse_value("4.7"), 4.7)

    def test_1k_lowercase(self):
        self.assertAlmostEqual(parse_value("1k"), 1_000.0)

    def test_1m_milli(self):
        self.assertAlmostEqual(parse_value("1m"), 0.001)

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            parse_value("xyz_bad")

    def test_4r7_not_valid_but_gives_4_7_or_raises(self):
        """'r' is not an SI prefix — should raise."""
        with self.assertRaises(ValueError):
            parse_value("4r7")


# ─── 2. MockCatalogue ────────────────────────────────────────────────────────

class TestMockCatalogue(unittest.TestCase):

    def setUp(self):
        self.cat = _mock_cat()

    def test_fixture_loads(self):
        self.assertGreater(len(self.cat._parts), 0)

    def test_search_resistor_0603_10k_returns_result(self):
        results = self.cat.search("Resistor", "10k", "0603")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["package"], "0603")

    def test_search_resistor_0402_10k(self):
        results = self.cat.search("Resistor", "10k", "0402")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["package"], "0402")

    def test_search_package_mismatch_returns_empty(self):
        """0201 package doesn't exist in fixture → empty list."""
        results = self.cat.search("Resistor", "10k", "0201")
        self.assertEqual(results, [])

    def test_search_part_type_case_insensitive(self):
        results = self.cat.search("resistor", "10k", "0603")
        self.assertGreater(len(results), 0)

    def test_search_unknown_part_type(self):
        results = self.cat.search("Inductor", "10u", "0603")
        self.assertEqual(results, [])

    def test_search_no_value_returns_all_in_package(self):
        """Value=None → match only on part_type + package."""
        results = self.cat.search("Resistor", None, "0603")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertEqual(r["package"], "0603")

    def test_search_no_package_returns_all_values(self):
        """Package=None → match only on part_type + value."""
        results = self.cat.search("Resistor", "10k", None)
        self.assertGreater(len(results), 0)

    def test_results_sorted_by_stock_desc(self):
        """Best-match is highest-stock candidate."""
        results = self.cat.search("Resistor", "10k", None)
        stocks = [r.get("stock", 0) for r in results]
        self.assertEqual(stocks, sorted(stocks, reverse=True))

    def test_value_tolerance_within_5pct(self):
        """9 900 Ω is within ±5 % of 10 000 Ω → should match."""
        results = self.cat.search("Resistor", "9900", "0603")
        # 9900 / 10000 = 99 % — within 5 % tolerance
        self.assertGreater(len(results), 0)

    def test_value_tolerance_outside_5pct(self):
        """8 000 Ω is >5 % away from 10 000 Ω → no 10k part returned."""
        results = self.cat.search("Resistor", "8000", "0603")
        # All 0603 resistors: 10k, 100k, 4.7, 470. None within 5 % of 8 000.
        values = [r.get("value_ohms") for r in results]
        for v in values:
            if v is not None:
                ratio = abs(8000 - v) / abs(v) if v != 0 else float("inf")
                self.assertGreater(ratio, 0.05)


# ─── 3. resolve_component ────────────────────────────────────────────────────

class TestResolveComponent(unittest.TestCase):

    def setUp(self):
        set_catalogue(_mock_cat())

    def tearDown(self):
        set_catalogue(None)

    def test_happy_path_resistor_0603_10k(self):
        result = resolve_component({"part": "Resistor", "value": "10k", "package": "0603"})
        self.assertTrue(result["resolved"])
        self.assertIn("mfr_part", result)
        self.assertIn("footprint", result)
        self.assertIn("datasheet_url", result)
        self.assertIn("lcsc_id", result)
        self.assertEqual(result["package"], "0603")

    def test_happy_path_returns_jlcpcb_part(self):
        """The fixture provider is 'jlcpcb'; resolved part should come from it."""
        result = resolve_component({"part": "Resistor", "value": "10k", "package": "0603"})
        self.assertTrue(result["resolved"])
        self.assertEqual(result["provider"], "jlcpcb")

    def test_no_match_returns_resolved_false(self):
        result = resolve_component({"part": "Resistor", "value": "10k", "package": "0201"})
        self.assertFalse(result["resolved"])
        self.assertIn("warning", result)
        self.assertIsInstance(result["warning"], str)
        self.assertGreater(len(result["warning"]), 0)

    def test_no_match_warning_contains_part_info(self):
        # 33k is not within 5% of any part in the fixture
        result = resolve_component({"part": "Resistor", "value": "33k", "package": "0603"})
        self.assertFalse(result["resolved"])
        warning = result["warning"].lower()
        self.assertIn("resistor", warning)

    def test_no_match_preserves_spec(self):
        # 33k is not within 5% of any part in the fixture (10k, 100k, 4.7, 470, 1k)
        spec = {"part": "Resistor", "value": "33k", "package": "0603"}
        result = resolve_component(spec)
        self.assertFalse(result["resolved"])
        self.assertEqual(result["spec"], spec)

    def test_missing_part_key(self):
        result = resolve_component({"value": "10k", "package": "0603"})
        self.assertFalse(result["resolved"])
        self.assertIn("warning", result)

    def test_empty_spec(self):
        result = resolve_component({})
        self.assertFalse(result["resolved"])
        self.assertIn("warning", result)

    def test_resolved_has_price_and_stock(self):
        result = resolve_component({"part": "Resistor", "value": "10k", "package": "0603"})
        self.assertTrue(result["resolved"])
        self.assertIn("price_usd", result)
        self.assertIn("stock", result)

    def test_package_mismatch_returns_unresolved(self):
        result = resolve_component({"part": "Resistor", "value": "10k", "package": "0201"})
        self.assertFalse(result["resolved"])

    def test_unknown_part_type_unresolved(self):
        result = resolve_component({"part": "Transistor", "value": "2N7002", "package": "SOT-23"})
        self.assertFalse(result["resolved"])


# ─── 4. resolve_many ─────────────────────────────────────────────────────────

class TestResolveMany(unittest.TestCase):

    def setUp(self):
        set_catalogue(_mock_cat())

    def tearDown(self):
        set_catalogue(None)

    def test_batch_returns_list_of_same_length(self):
        specs = [
            {"part": "Resistor", "value": "10k", "package": "0603"},
            {"part": "Resistor", "value": "10k", "package": "0402"},
            {"part": "Resistor", "value": "33k", "package": "0201"},  # no-match
        ]
        results = resolve_many(specs)
        self.assertEqual(len(results), 3)

    def test_batch_mixed_resolved_and_unresolved(self):
        specs = [
            {"part": "Resistor", "value": "10k", "package": "0603"},  # match
            {"part": "Resistor", "value": "10k", "package": "0201"},  # no-match
        ]
        results = resolve_many(specs)
        self.assertTrue(results[0]["resolved"])
        self.assertFalse(results[1]["resolved"])

    def test_empty_list_returns_empty(self):
        self.assertEqual(resolve_many([]), [])


# ─── 5. Live-mode skipped in CI ──────────────────────────────────────────────

class TestLiveModeGating(unittest.TestCase):

    def test_live_mode_not_active_by_default(self):
        """KERF_DISTRIBUTOR_LIVE must not be set in the test environment."""
        val = os.environ.get("KERF_DISTRIBUTOR_LIVE", "")
        self.assertNotEqual(val.strip(), "1",
                            "KERF_DISTRIBUTOR_LIVE=1 is set — live tests would run")


if __name__ == "__main__":
    unittest.main()
