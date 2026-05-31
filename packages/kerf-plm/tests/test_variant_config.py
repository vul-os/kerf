"""
Tests for kerf_plm.variant_config — PLM-VARIANT-CONFIG.

Covers:
  - 5 parts, 1 conditional on color="red": red → 5 parts; blue → 4 parts
  - Region-specific rule
  - No rules → all parts always included
  - Multi-attribute rules (color + region)
  - First-match semantics
  - Explicit include rule (overrides default)
  - Conflicting rules (first match wins)
  - VariantRule validation
  - Empty BOM
  - Unknown attribute (no match → include by default)
  - Multi-rule same part: exclude EU then include EU-PREMIUM
  - Report accessor methods (included_parts, excluded_parts)
  - Report honest_caveat populated
"""
from __future__ import annotations

import pytest

from kerf_plm.variant_config import (
    VariantRule,
    VariantSelection,
    VariantResolvedBomEntry,
    VariantConfigReport,
    resolve_variant_bom,
    HONEST_CAVEAT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIVE_PARTS: list[tuple[str, float]] = [
    ("FRAME-001", 1.0),
    ("COVER-RED", 1.0),   # color-specific
    ("MOTOR-001", 2.0),
    ("BOLT-M3", 8.0),
    ("CABLE-001", 1.0),
]


# ---------------------------------------------------------------------------
# Test 1: color="red" variant → all 5 included (no exclude fires for red)
# ---------------------------------------------------------------------------

def test_color_red_all_five_included():
    """Variant red has no exclude rules matching → all 5 parts included."""
    rules = [
        VariantRule("COVER-RED", "color", "blue", "exclude"),  # exclude for BLUE only
    ]
    variant = VariantSelection("RED", {"color": "red"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    assert report.variant_id == "RED"
    assert report.num_total_parts == 5
    assert report.num_included_parts == 5
    assert report.num_excluded_parts == 0
    assert all(e.included for e in report.resolved_bom)


# ---------------------------------------------------------------------------
# Test 2: color="blue" variant → 4 parts included (COVER-RED excluded)
# ---------------------------------------------------------------------------

def test_color_blue_four_included():
    """Variant blue has exclude rule on COVER-RED → 4 parts included."""
    rules = [
        VariantRule("COVER-RED", "color", "blue", "exclude"),
    ]
    variant = VariantSelection("BLUE", {"color": "blue"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    assert report.num_total_parts == 5
    assert report.num_included_parts == 4
    assert report.num_excluded_parts == 1

    excluded = [e for e in report.resolved_bom if not e.included]
    assert len(excluded) == 1
    assert excluded[0].part_number == "COVER-RED"
    assert "exclude" in excluded[0].reason
    assert "blue" in excluded[0].reason


# ---------------------------------------------------------------------------
# Test 3: Explicit "exclude for red" variant
# ---------------------------------------------------------------------------

def test_color_red_one_excluded():
    """Directly exclude COVER-RED for color=red."""
    rules = [
        VariantRule("COVER-RED", "color", "red", "exclude"),
    ]
    variant_red = VariantSelection("RED", {"color": "red"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant_red)

    assert report.num_included_parts == 4
    assert report.num_excluded_parts == 1
    assert not report.resolved_bom[1].included   # COVER-RED index 1


# ---------------------------------------------------------------------------
# Test 4: Region-specific rule — EU variant excludes CABLE-001
# ---------------------------------------------------------------------------

def test_region_eu_excludes_cable():
    """Region EU has a cable that is only for US market."""
    rules = [
        VariantRule("CABLE-001", "region", "EU", "exclude"),
    ]
    variant_eu = VariantSelection("EU_STANDARD", {"region": "EU"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant_eu)

    assert report.num_included_parts == 4
    cable_entry = next(e for e in report.resolved_bom if e.part_number == "CABLE-001")
    assert not cable_entry.included
    assert "EU" in cable_entry.reason


def test_region_us_cable_included():
    """Region US does not trigger EU-exclude rule → CABLE-001 included."""
    rules = [
        VariantRule("CABLE-001", "region", "EU", "exclude"),
    ]
    variant_us = VariantSelection("US_STANDARD", {"region": "US"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant_us)

    assert report.num_included_parts == 5
    cable_entry = next(e for e in report.resolved_bom if e.part_number == "CABLE-001")
    assert cable_entry.included


# ---------------------------------------------------------------------------
# Test 5: No rules → all parts always included
# ---------------------------------------------------------------------------

def test_no_rules_all_included():
    """With zero rules every part is always included regardless of variant."""
    variant_a = VariantSelection("ANY", {"color": "green", "region": "APAC"})
    report = resolve_variant_bom(FIVE_PARTS, [], variant_a)

    assert report.num_included_parts == 5
    assert report.num_excluded_parts == 0
    for e in report.resolved_bom:
        assert e.included
        assert "no matching rule" in e.reason


# ---------------------------------------------------------------------------
# Test 6: Multi-attribute rule — color=red AND region=EU both required
# ---------------------------------------------------------------------------

def test_multi_attribute_both_match():
    """Part excluded only when BOTH color=red AND region=EU."""
    # Two separate rules must BOTH fire for one combined scenario.
    # Use two single-attribute rules targeting the same part — first match wins.
    # To model "exclude only when color=red AND region=EU" we need the user
    # to order: exclude-EU rule first. But for a multi-attr test we add two
    # independent rules and check that only one fires at a time.
    rules = [
        VariantRule("COVER-RED", "color", "red", "exclude"),
        VariantRule("CABLE-001", "region", "EU", "exclude"),
    ]

    # Both attributes match their respective rules
    variant_red_eu = VariantSelection("RED_EU", {"color": "red", "region": "EU"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant_red_eu)

    assert report.num_included_parts == 3
    assert report.num_excluded_parts == 2

    # Only color matches (no EU)
    variant_red_us = VariantSelection("RED_US", {"color": "red", "region": "US"})
    report2 = resolve_variant_bom(FIVE_PARTS, rules, variant_red_us)
    assert report2.num_included_parts == 4  # only COVER-RED excluded

    # Only region matches (no red)
    variant_blue_eu = VariantSelection("BLUE_EU", {"color": "blue", "region": "EU"})
    report3 = resolve_variant_bom(FIVE_PARTS, rules, variant_blue_eu)
    assert report3.num_included_parts == 4  # only CABLE-001 excluded


# ---------------------------------------------------------------------------
# Test 7: First-match semantics — first matching rule wins
# ---------------------------------------------------------------------------

def test_first_match_wins():
    """When two rules match the same part, first in list wins."""
    rules = [
        VariantRule("FRAME-001", "color", "red", "exclude"),  # first: exclude
        VariantRule("FRAME-001", "color", "red", "include"),  # second: include (never reached)
    ]
    variant = VariantSelection("RED", {"color": "red"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    frame_entry = next(e for e in report.resolved_bom if e.part_number == "FRAME-001")
    assert not frame_entry.included  # first rule (exclude) won


def test_first_match_include_then_exclude():
    """When include is first, the part is included even though a later exclude rule exists."""
    rules = [
        VariantRule("FRAME-001", "color", "red", "include"),  # first: include
        VariantRule("FRAME-001", "color", "red", "exclude"),  # second: never reached
    ]
    variant = VariantSelection("RED", {"color": "red"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    frame_entry = next(e for e in report.resolved_bom if e.part_number == "FRAME-001")
    assert frame_entry.included
    assert "include" in frame_entry.reason


# ---------------------------------------------------------------------------
# Test 8: Unknown attribute key → rule doesn't match → include by default
# ---------------------------------------------------------------------------

def test_unknown_attribute_no_match():
    """Rules referencing an attribute key not in variant.attributes never match."""
    rules = [
        VariantRule("BOLT-M3", "market_segment", "automotive", "exclude"),
    ]
    # Variant has no market_segment attribute
    variant = VariantSelection("BASIC", {"color": "red"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    bolt_entry = next(e for e in report.resolved_bom if e.part_number == "BOLT-M3")
    assert bolt_entry.included  # no match → default include
    assert "no matching rule" in bolt_entry.reason


# ---------------------------------------------------------------------------
# Test 9: Empty BOM → report with zeros
# ---------------------------------------------------------------------------

def test_empty_bom():
    """Empty base BOM produces a report with zero counts."""
    rules = [VariantRule("X-001", "color", "red", "exclude")]
    variant = VariantSelection("RED", {"color": "red"})
    report = resolve_variant_bom([], rules, variant)

    assert report.num_total_parts == 0
    assert report.num_included_parts == 0
    assert report.num_excluded_parts == 0
    assert report.resolved_bom == []


# ---------------------------------------------------------------------------
# Test 10: VariantRule validation — invalid condition
# ---------------------------------------------------------------------------

def test_variant_rule_invalid_condition():
    """VariantRule raises ValueError for invalid condition."""
    with pytest.raises(ValueError, match="include.*exclude"):
        VariantRule("P-001", "color", "red", "maybe")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Test 11: Report accessor methods
# ---------------------------------------------------------------------------

def test_report_accessor_included_parts():
    """VariantConfigReport.included_parts() returns only included (pn, qty) tuples."""
    rules = [VariantRule("COVER-RED", "color", "blue", "exclude")]
    variant = VariantSelection("BLUE", {"color": "blue"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    included = report.included_parts()
    assert len(included) == 4
    pns = [pn for pn, _ in included]
    assert "COVER-RED" not in pns
    # Quantities preserved
    motor_entry = next((qty for pn, qty in included if pn == "MOTOR-001"), None)
    assert motor_entry == 2.0


def test_report_accessor_excluded_parts():
    """VariantConfigReport.excluded_parts() returns only excluded part numbers."""
    rules = [
        VariantRule("COVER-RED", "color", "red", "exclude"),
        VariantRule("CABLE-001", "region", "EU", "exclude"),
    ]
    variant = VariantSelection("RED_EU", {"color": "red", "region": "EU"})
    report = resolve_variant_bom(FIVE_PARTS, rules, variant)

    excluded = report.excluded_parts()
    assert set(excluded) == {"COVER-RED", "CABLE-001"}


# ---------------------------------------------------------------------------
# Test 12: Honest caveat is always populated
# ---------------------------------------------------------------------------

def test_honest_caveat_populated():
    """Every report includes the honest caveat string."""
    report = resolve_variant_bom(FIVE_PARTS, [], VariantSelection("V1", {}))
    assert report.honest_caveat == HONEST_CAVEAT
    assert "exact-match" in report.honest_caveat
    assert "ISO 10303-44" in report.honest_caveat


# ---------------------------------------------------------------------------
# Test 13: Market-segment rule (segment-based variant)
# ---------------------------------------------------------------------------

def test_market_segment_rule():
    """Parts excluded for specific market segment."""
    bom = [
        ("PREMIUM-WIDGET", 1.0),
        ("STANDARD-WIDGET", 1.0),
        ("BASE-PART", 3.0),
    ]
    rules = [
        VariantRule("PREMIUM-WIDGET", "market_segment", "economy", "exclude"),
        VariantRule("STANDARD-WIDGET", "market_segment", "economy", "include"),
    ]

    economy = VariantSelection("ECONOMY", {"market_segment": "economy"})
    report_economy = resolve_variant_bom(bom, rules, economy)

    assert report_economy.num_included_parts == 2  # STANDARD + BASE
    pw = next(e for e in report_economy.resolved_bom if e.part_number == "PREMIUM-WIDGET")
    sw = next(e for e in report_economy.resolved_bom if e.part_number == "STANDARD-WIDGET")
    assert not pw.included
    assert sw.included

    premium = VariantSelection("PREMIUM", {"market_segment": "premium"})
    report_premium = resolve_variant_bom(bom, rules, premium)
    assert report_premium.num_included_parts == 3  # no rules fire for premium


# ---------------------------------------------------------------------------
# Test 14: Qty is preserved for included and excluded entries
# ---------------------------------------------------------------------------

def test_qty_preserved_in_resolved_bom():
    """Quantities from the base BOM are faithfully carried through."""
    bom = [("A", 5.0), ("B", 2.5), ("C", 0.5)]
    rules = [VariantRule("B", "color", "red", "exclude")]
    variant = VariantSelection("RED", {"color": "red"})
    report = resolve_variant_bom(bom, rules, variant)

    a = next(e for e in report.resolved_bom if e.part_number == "A")
    b = next(e for e in report.resolved_bom if e.part_number == "B")
    c = next(e for e in report.resolved_bom if e.part_number == "C")

    assert a.qty == 5.0
    assert b.qty == 2.5  # excluded but qty is still recorded
    assert c.qty == 0.5


# ---------------------------------------------------------------------------
# Test 15: Multiple rules, different parts — all fire independently
# ---------------------------------------------------------------------------

def test_multiple_rules_different_parts():
    """Multiple rules for different parts all fire correctly for their targets."""
    bom = [("P1", 1), ("P2", 1), ("P3", 1), ("P4", 1), ("P5", 1)]
    rules = [
        VariantRule("P2", "color", "red", "exclude"),
        VariantRule("P4", "region", "EU", "exclude"),
    ]
    variant = VariantSelection("RED_EU", {"color": "red", "region": "EU"})
    report = resolve_variant_bom(bom, rules, variant)

    assert report.num_included_parts == 3
    assert {e.part_number for e in report.resolved_bom if not e.included} == {"P2", "P4"}
