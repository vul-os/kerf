"""
Test suite: GDT-COMPOSITE-TOLERANCE-FRAME
ASME Y14.5-2018 §10.5 composite position tolerance (PLTZF / FRTZF).

Oracle cases derived from ASME Y14.5-2018 §10.5 text and figures:
  §10.5 Fig. 10-24 -- PLTZF: pos|D0.5|A|B|C / FRTZF: pos|D0.2|A  -> VALID
  §10.5 Fig. 10-25 -- FRTZF primary not matching PLTZF primary     -> FAIL R3
  §10.5 Fig. 10-26 -- FRTZF with secondary/tertiary subset omission -> VALID
  §10.5 Note 2     -- FRTZF tol > PLTZF tol                         -> FAIL R2
  §10.5.1          -- Degenerate: single-line / malformed text       -> parse error
  §10.5.1(b)       -- FRTZF datum not present in PLTZF               -> FAIL R4
  §10.5.1          -- Symbol mismatch between lines                  -> FAIL R5

Rule citations:
  R1  §10.5.1       -- Two lines required
  R2  §10.5.1 Note2 -- FRTZF tolerance ≤ PLTZF tolerance
  R3  §10.5.1(a)    -- FRTZF primary datum matches PLTZF primary
  R4  §10.5.1(b)    -- FRTZF datums subset of PLTZF datums in order
  R5  §10.5.1       -- Symbol match
"""

import json

import pytest

from kerf_gdnt.composite_tolerance import (
    CompositeFrame,
    CompositeValidationReport,
    ToleranceFrameLine,
    parse_composite_frame,
    validate_composite_frame,
)
from kerf_gdnt.tools import (
    gdt_validate_composite_tolerance_frame_spec,
    run_gdt_validate_composite_tolerance_frame,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line(symbol, tol, *, dia=True, mod=None, datums=None):
    return ToleranceFrameLine(
        symbol=symbol,
        tolerance_value=tol,
        diameter_zone=dia,
        modifier=mod,
        datums=datums or [],
    )


def _tool(frame_text):
    """Call LLM tool directly and decode JSON."""
    return json.loads(run_gdt_validate_composite_tolerance_frame(
        {"frame_text": frame_text}, ctx=None,
    ))


# ---------------------------------------------------------------------------
# T1: Valid composite — §10.5 Fig. 10-24 style
# PLTZF: position|D0.5|A|B|C  /  FRTZF: position|D0.2|A
# FRTZF primary A matches PLTZF primary A -> VALID
# ---------------------------------------------------------------------------

class TestValidComposite:
    def test_parse_two_lines(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A")
        assert frame.pltzf.symbol == "position"
        assert frame.pltzf.tolerance_value == 0.5
        assert frame.pltzf.datums == ["A", "B", "C"]
        assert frame.frtzf.tolerance_value == 0.2
        assert frame.frtzf.datums == ["A"]

    def test_valid_report(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A")
        report = validate_composite_frame(frame)
        assert report.valid is True
        assert report.violations == []

    def test_tool_valid(self):
        result = _tool("position|D0.5|A|B|C / position|D0.2|A")
        assert result["valid"] is True
        assert result["violations"] == []
        assert result["pltzf"]["tolerance_value"] == 0.5
        assert result["frtzf"]["tolerance_value"] == 0.2

    def test_frtzf_missing_secondary_valid(self):
        """FRTZF may omit secondary/tertiary datums (§10.5.1(b) — less restrictive)."""
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A|B")
        report = validate_composite_frame(frame)
        assert report.valid is True
        # FRTZF has A|B — valid subset of PLTZF A|B|C in same order.

    def test_frtzf_no_datums_valid_with_warning(self):
        """FRTZF with no datum refs is permitted — only feature-to-feature control."""
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2")
        report = validate_composite_frame(frame)
        assert report.valid is True
        assert any("float freely" in w for w in report.warnings)

    def test_equal_tolerances_valid(self):
        """FRTZF == PLTZF tolerance is exactly on the boundary — permitted."""
        frame = parse_composite_frame("position|D0.5|A|B / position|D0.5|A")
        report = validate_composite_frame(frame)
        assert report.valid is True


# ---------------------------------------------------------------------------
# T2: Mismatched primary datum — R3 §10.5.1(a)
# PLTZF: A|B|C  /  FRTZF: B (B is not the primary datum of PLTZF)
# ---------------------------------------------------------------------------

class TestMismatchedPrimaryDatum:
    def test_frtzf_primary_B_not_A(self):
        """FRTZF primary B does not match PLTZF primary A -> FAIL."""
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|B")
        report = validate_composite_frame(frame)
        assert report.valid is False
        codes = [v.code for v in report.violations]
        assert "FRTZF_PRIMARY_DATUM_MISMATCH" in codes

    def test_violation_cites_10_5_1a(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|B")
        report = validate_composite_frame(frame)
        v = next(v for v in report.violations if v.code == "FRTZF_PRIMARY_DATUM_MISMATCH")
        assert "§10.5.1(a)" in v.rule

    def test_violation_message_mentions_both_datums(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|B")
        report = validate_composite_frame(frame)
        v = next(v for v in report.violations if v.code == "FRTZF_PRIMARY_DATUM_MISMATCH")
        assert "B" in v.message and "A" in v.message

    def test_tool_returns_violation(self):
        result = _tool("position|D0.5|A|B|C / position|D0.2|B")
        assert result["valid"] is False
        codes = [v["code"] for v in result["violations"]]
        assert "FRTZF_PRIMARY_DATUM_MISMATCH" in codes


# ---------------------------------------------------------------------------
# T3: FRTZF tolerance exceeds PLTZF — R2 §10.5.1 Note 2
# ---------------------------------------------------------------------------

class TestFRTZFToleranceTooLarge:
    def test_frtzf_tol_exceeds_pltzf(self):
        frame = parse_composite_frame("position|D0.2|A|B / position|D0.5|A")
        report = validate_composite_frame(frame)
        assert report.valid is False
        codes = [v.code for v in report.violations]
        assert "FRTZF_TOL_EXCEEDS_PLTZF" in codes

    def test_violation_cites_note2(self):
        frame = parse_composite_frame("position|D0.2|A|B / position|D0.5|A")
        report = validate_composite_frame(frame)
        v = next(v for v in report.violations if v.code == "FRTZF_TOL_EXCEEDS_PLTZF")
        assert "Note 2" in v.rule

    def test_tool_violation(self):
        result = _tool("position|D0.2|A|B / position|D0.5|A")
        assert result["valid"] is False
        assert any(v["code"] == "FRTZF_TOL_EXCEEDS_PLTZF" for v in result["violations"])


# ---------------------------------------------------------------------------
# T4: FRTZF datum not in PLTZF — R4 §10.5.1(b)
# FRTZF references datum D, which is absent from PLTZF A|B|C
# ---------------------------------------------------------------------------

class TestFRTZFDatumNotInPLTZF:
    def test_frtzf_introduces_new_datum(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A|D")
        report = validate_composite_frame(frame)
        assert report.valid is False
        codes = [v.code for v in report.violations]
        assert "FRTZF_DATUM_NOT_IN_PLTZF" in codes

    def test_violation_cites_10_5_1b(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A|D")
        report = validate_composite_frame(frame)
        v = next(v for v in report.violations if v.code == "FRTZF_DATUM_NOT_IN_PLTZF")
        assert "§10.5.1(b)" in v.rule


# ---------------------------------------------------------------------------
# T5: Degenerate single-line frame — R1 §10.5.1
# ---------------------------------------------------------------------------

class TestDegenerateSingleLine:
    def test_no_slash_raises_value_error(self):
        with pytest.raises(ValueError, match="two lines"):
            parse_composite_frame("position|D0.5|A|B|C")

    def test_three_lines_raises_value_error(self):
        with pytest.raises(ValueError):
            parse_composite_frame("position|D0.5|A / position|D0.2|A / position|D0.1|A")

    def test_tool_returns_error_payload_on_bad_text(self):
        result = _tool("not_a_composite_frame")
        # Should return an error dict, not raise
        assert "error" in result or result.get("valid") is False or "code" in result


# ---------------------------------------------------------------------------
# T6: Symbol mismatch — R5 §10.5.1
# ---------------------------------------------------------------------------

class TestSymbolMismatch:
    def test_position_vs_flatness(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / flatness|D0.2|A")
        report = validate_composite_frame(frame)
        assert report.valid is False
        codes = [v.code for v in report.violations]
        assert "SYMBOL_MISMATCH" in codes

    def test_symbol_mismatch_cites_10_5_1(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / flatness|D0.2|A")
        report = validate_composite_frame(frame)
        v = next(v for v in report.violations if v.code == "SYMBOL_MISMATCH")
        assert "§10.5.1" in v.rule


# ---------------------------------------------------------------------------
# T7: FRTZF datum order violation — R4 §10.5.1(b)
# PLTZF: A|B|C -> FRTZF: A|C|B (out of precedence order)
# ---------------------------------------------------------------------------

class TestFRTZFDatumOrderViolation:
    def test_reversed_order(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A|C|B")
        report = validate_composite_frame(frame)
        assert report.valid is False
        codes = [v.code for v in report.violations]
        assert "FRTZF_DATUM_ORDER_VIOLATION" in codes

    def test_order_violation_cites_10_5_1b(self):
        frame = parse_composite_frame("position|D0.5|A|B|C / position|D0.2|A|C|B")
        report = validate_composite_frame(frame)
        v = next(v for v in report.violations if v.code == "FRTZF_DATUM_ORDER_VIOLATION")
        assert "§10.5.1(b)" in v.rule


# ---------------------------------------------------------------------------
# T8: Tool spec sanity
# ---------------------------------------------------------------------------

class TestToolSpec:
    def test_spec_name(self):
        assert gdt_validate_composite_tolerance_frame_spec.name == (
            "gdt_validate_composite_tolerance_frame"
        )

    def test_spec_has_frame_text_param(self):
        props = gdt_validate_composite_tolerance_frame_spec.input_schema["properties"]
        assert "frame_text" in props

    def test_spec_required_frame_text(self):
        required = gdt_validate_composite_tolerance_frame_spec.input_schema["required"]
        assert "frame_text" in required

    def test_tool_returns_pltzf_and_frtzf_in_payload(self):
        result = _tool("position|D0.5|A|B|C / position|D0.2|A")
        assert "pltzf" in result
        assert "frtzf" in result
