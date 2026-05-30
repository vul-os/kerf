"""
Tests for PLM effectivity BOM expansion.

Covers:
  1. Date-only filter (lines in/out of date window)
  2. Option-only filter (exact key=value match)
  3. Combined date + option filter -- the depth-bar examples from the spec
  4. No-filter expansion (lines without option_requirements pass)
  5. Empty result when effective_date is outside all line ranges
  6. ISO 10303-44 example: three-way date/serial/option compound effectivity
  7. Serial-number range filter (integer comparison)
  8. Serial-number range filter (lexicographic fallback)
  9. Option with un-met requirement excluded
 10. Partial option match excluded (all requirements must pass)
 11. Open-ended effective_from bound (no lower limit)
 12. Open-ended effective_to bound (no upper limit)
 13. HONEST_FLAG is present on result
 14. part_ids() helper returns correct ordered list
 15. Tool-layer: valid JSON round-trip via run_plm_expand_effectivity_bom (v6)
 16. Tool-layer: valid JSON round-trip via run_plm_expand_effectivity_bom (v8)
 17. Tool-layer: missing bom_lines returns BAD_ARGS
 18. Tool-layer: invalid effective_date returns BAD_ARGS
"""

from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from kerf_plm.effectivity_bom import (
    BomLine,
    EffectivityFilter,
    ExpandedBom,
    HONEST_FLAG,
    expand_effectivity_bom,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx():
    try:
        from kerf_plm._compat import ProjectCtx
        return ProjectCtx()
    except ImportError:
        return None


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Depth-bar BOM fixture (spec example)
# ---------------------------------------------------------------------------

@pytest.fixture
def depth_bar_bom():
    return [
        BomLine("A", description="Axle assembly", qty=2,
                effective_from=date(2025, 1, 1), effective_to=date(2026, 12, 31)),
        BomLine("B", description="V6 engine mount", qty=1,
                option_requirements={"engine": "v6"}),
        BomLine("C", description="Chassis bracket", qty=4),
    ]


# ---------------------------------------------------------------------------
# Test 1 -- Date-only filter
# ---------------------------------------------------------------------------

def test_date_filter_inside_range(depth_bar_bom):
    """Line A is valid on 2026-03-15; B excluded (no engine option); C always valid."""
    result = expand_effectivity_bom(
        depth_bar_bom,
        effective_date=date(2026, 3, 15),
        options={},
    )
    ids = result.part_ids()
    assert "A" in ids
    assert "C" in ids
    assert "B" not in ids


def test_date_filter_before_range():
    """Line with effective_from=2025-01-01 is excluded for date 2024-12-31."""
    lines = [
        BomLine("X", qty=1, effective_from=date(2025, 1, 1)),
        BomLine("Y", qty=2),
    ]
    result = expand_effectivity_bom(lines, effective_date=date(2024, 12, 31))
    assert result.part_ids() == ["Y"]
    assert result.total_qty == 2


def test_date_filter_after_range():
    """Line with effective_to=2026-12-31 is excluded for date 2027-01-01."""
    lines = [
        BomLine("X", qty=1, effective_to=date(2026, 12, 31)),
        BomLine("Y", qty=3),
    ]
    result = expand_effectivity_bom(lines, effective_date=date(2027, 1, 1))
    assert result.part_ids() == ["Y"]


# ---------------------------------------------------------------------------
# Test 2 -- Option-only filter
# ---------------------------------------------------------------------------

def test_option_filter_match():
    """Line with option_requirements={engine: v6} is included when engine=v6."""
    lines = [
        BomLine("ENG_V6", qty=1, option_requirements={"engine": "v6"}),
        BomLine("FRAME", qty=1),
    ]
    result = expand_effectivity_bom(lines, options={"engine": "v6"})
    assert set(result.part_ids()) == {"ENG_V6", "FRAME"}


def test_option_filter_no_match():
    """Line with option_requirements={engine: v6} is excluded when engine=v8."""
    lines = [
        BomLine("ENG_V6", qty=1, option_requirements={"engine": "v6"}),
        BomLine("FRAME", qty=1),
    ]
    result = expand_effectivity_bom(lines, options={"engine": "v8"})
    assert result.part_ids() == ["FRAME"]


# ---------------------------------------------------------------------------
# Test 3 -- Combined (depth-bar spec examples)
# ---------------------------------------------------------------------------

def test_combined_date_v8(depth_bar_bom):
    """date=2026-03-15, engine=v8: A (qty=2) + C (qty=4) = 6."""
    result = expand_effectivity_bom(
        depth_bar_bom,
        effective_date=date(2026, 3, 15),
        options={"engine": "v8"},
    )
    assert result.part_ids() == ["A", "C"]
    assert result.total_qty == 6


def test_combined_date_v6(depth_bar_bom):
    """date=2026-03-15, engine=v6: A (qty=2) + B (qty=1) + C (qty=4) = 7."""
    result = expand_effectivity_bom(
        depth_bar_bom,
        effective_date=date(2026, 3, 15),
        options={"engine": "v6"},
    )
    assert result.part_ids() == ["A", "B", "C"]
    assert result.total_qty == 7


# ---------------------------------------------------------------------------
# Test 4 -- No filter
# ---------------------------------------------------------------------------

def test_no_filter_passes_unconstrained_lines():
    """Lines without option_requirements pass; lines with requirements excluded
    when options selector is empty (no requirement can be satisfied)."""
    lines = [
        BomLine("P1", qty=1, effective_from=date(2020, 1, 1), effective_to=date(2021, 1, 1)),
        BomLine("P2", qty=2, option_requirements={"colour": "red"}),
        BomLine("P3", qty=3),
    ]
    result = expand_effectivity_bom(lines)
    # P1 and P3: no option_requirements, no date selector -> pass
    # P2: requires colour=red, selector options={} -> excluded
    assert result.part_ids() == ["P1", "P3"]
    assert result.total_qty == 4


# ---------------------------------------------------------------------------
# Test 5 -- Empty result (date out of all ranges)
# ---------------------------------------------------------------------------

def test_empty_result_date_out_of_range():
    """All lines have effective_to in the past; date in the future yields empty."""
    lines = [
        BomLine("A", qty=2, effective_to=date(2020, 12, 31)),
        BomLine("B", qty=1, effective_to=date(2021, 6, 30)),
    ]
    result = expand_effectivity_bom(lines, effective_date=date(2026, 1, 1))
    assert result.entries == []
    assert result.total_qty == 0


# ---------------------------------------------------------------------------
# Test 6 -- ISO 10303-44 compound effectivity
# ---------------------------------------------------------------------------

def test_iso_10303_44_compound_effectivity():
    """
    ISO 10303-44 ss5.3 compound effectivity example.
    Aviation spare-part kit: SN 1000+, date 2025-06-01, kit=extended.
    """
    lines = [
        BomLine("SEAL_A", qty=2, serial_from="1000"),
        BomLine("SEAL_EXTRA", qty=1, serial_from="1000",
                option_requirements={"kit": "extended"}),
        BomLine("SEAL_LEGACY", qty=2, serial_to="999"),
        BomLine("SEAL_FUTURE", qty=1, effective_from=date(2026, 1, 1)),
    ]

    result = expand_effectivity_bom(
        lines,
        effective_date=date(2025, 6, 1),
        options={"kit": "extended"},
        serial_number="1050",
    )
    ids = result.part_ids()
    assert "SEAL_A" in ids
    assert "SEAL_EXTRA" in ids
    assert "SEAL_LEGACY" not in ids
    assert "SEAL_FUTURE" not in ids
    assert result.total_qty == 3


# ---------------------------------------------------------------------------
# Test 7 -- Serial-number range (integer)
# ---------------------------------------------------------------------------

def test_serial_range_integer():
    lines = [
        BomLine("EARLY", qty=1, serial_from="1", serial_to="500"),
        BomLine("MID", qty=1, serial_from="501", serial_to="1000"),
        BomLine("ALWAYS", qty=1),
    ]
    result = expand_effectivity_bom(lines, serial_number="750")
    assert result.part_ids() == ["MID", "ALWAYS"]


# ---------------------------------------------------------------------------
# Test 8 -- Serial-number range (lexicographic)
# ---------------------------------------------------------------------------

def test_serial_range_lexicographic():
    lines = [
        BomLine("ALPHA_BATCH", qty=1, serial_from="AA001", serial_to="AA999"),
        BomLine("BETA_BATCH", qty=1, serial_from="AB000"),
    ]
    result = expand_effectivity_bom(lines, serial_number="AA500")
    assert result.part_ids() == ["ALPHA_BATCH"]


# ---------------------------------------------------------------------------
# Test 9 -- Un-met option requirement excluded
# ---------------------------------------------------------------------------

def test_option_unmet_excluded():
    lines = [
        BomLine("SPORT_WING", qty=1, option_requirements={"trim": "sport"}),
        BomLine("BASE_HOOD", qty=1),
    ]
    result = expand_effectivity_bom(lines, options={"trim": "base"})
    assert result.part_ids() == ["BASE_HOOD"]


# ---------------------------------------------------------------------------
# Test 10 -- Partial option match excluded (all requirements must pass)
# ---------------------------------------------------------------------------

def test_partial_option_match_excluded():
    """Line requires engine=v6 AND trim=sport; selector has engine=v6 only."""
    lines = [
        BomLine("SPORT_V6", qty=1, option_requirements={"engine": "v6", "trim": "sport"}),
        BomLine("BASE", qty=1),
    ]
    result = expand_effectivity_bom(lines, options={"engine": "v6"})
    assert result.part_ids() == ["BASE"]


# ---------------------------------------------------------------------------
# Test 11 -- Open-ended effective_from (no lower bound)
# ---------------------------------------------------------------------------

def test_open_effective_from():
    lines = [BomLine("UNIVERSAL", qty=1, effective_to=date(2099, 12, 31))]
    result = expand_effectivity_bom(lines, effective_date=date(1990, 1, 1))
    assert result.part_ids() == ["UNIVERSAL"]


# ---------------------------------------------------------------------------
# Test 12 -- Open-ended effective_to (no upper bound)
# ---------------------------------------------------------------------------

def test_open_effective_to():
    lines = [BomLine("FUTURE_FOREVER", qty=1, effective_from=date(2026, 1, 1))]
    result = expand_effectivity_bom(lines, effective_date=date(2050, 1, 1))
    assert result.part_ids() == ["FUTURE_FOREVER"]


# ---------------------------------------------------------------------------
# Test 13 -- HONEST_FLAG present
# ---------------------------------------------------------------------------

def test_honest_flag_on_result():
    result = expand_effectivity_bom([BomLine("X", qty=1)])
    assert result.honest_flag == HONEST_FLAG
    assert "v1" in result.honest_flag
    assert "exact" in result.honest_flag.lower()


# ---------------------------------------------------------------------------
# Test 14 -- part_ids() helper
# ---------------------------------------------------------------------------

def test_part_ids_helper():
    lines = [BomLine("P1", qty=1), BomLine("P2", qty=2), BomLine("P3", qty=3)]
    result = expand_effectivity_bom(lines)
    assert result.part_ids() == ["P1", "P2", "P3"]


# ---------------------------------------------------------------------------
# Test 15 -- Tool layer: valid JSON round-trip (v6)
# ---------------------------------------------------------------------------

def test_tool_layer_valid_v6():
    from kerf_plm._tools_module import run_plm_expand_effectivity_bom

    payload = {
        "bom_lines": [
            {"part_id": "A", "qty": 2,
             "effective_from": "2025-01-01", "effective_to": "2026-12-31"},
            {"part_id": "B", "qty": 1,
             "option_requirements": {"engine": "v6"}},
            {"part_id": "C", "qty": 4},
        ],
        "effective_date": "2026-03-15",
        "options": {"engine": "v6"},
    }
    result_json = run(run_plm_expand_effectivity_bom(_ctx(), json.dumps(payload).encode()))
    result = json.loads(result_json)
    assert result["entry_count"] == 3
    assert result["total_qty"] == 7
    assert "honest_flag" in result


# ---------------------------------------------------------------------------
# Test 16 -- Tool layer: valid JSON round-trip (v8)
# ---------------------------------------------------------------------------

def test_tool_layer_valid_v8():
    from kerf_plm._tools_module import run_plm_expand_effectivity_bom

    payload = {
        "bom_lines": [
            {"part_id": "A", "qty": 2,
             "effective_from": "2025-01-01", "effective_to": "2026-12-31"},
            {"part_id": "B", "qty": 1,
             "option_requirements": {"engine": "v6"}},
            {"part_id": "C", "qty": 4},
        ],
        "effective_date": "2026-03-15",
        "options": {"engine": "v8"},
    }
    result_json = run(run_plm_expand_effectivity_bom(_ctx(), json.dumps(payload).encode()))
    result = json.loads(result_json)
    assert result["entry_count"] == 2
    assert result["total_qty"] == 6


# ---------------------------------------------------------------------------
# Test 17 -- Tool layer: missing bom_lines -> BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_layer_missing_bom_lines():
    from kerf_plm._tools_module import run_plm_expand_effectivity_bom

    result_json = run(run_plm_expand_effectivity_bom(_ctx(), b"{}"))
    result = json.loads(result_json)
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# Test 18 -- Tool layer: invalid effective_date -> BAD_ARGS
# ---------------------------------------------------------------------------

def test_tool_layer_invalid_date():
    from kerf_plm._tools_module import run_plm_expand_effectivity_bom

    payload = {
        "bom_lines": [{"part_id": "X", "qty": 1}],
        "effective_date": "not-a-date",
    }
    result_json = run(run_plm_expand_effectivity_bom(_ctx(), json.dumps(payload).encode()))
    result = json.loads(result_json)
    assert result.get("code") == "BAD_ARGS"
