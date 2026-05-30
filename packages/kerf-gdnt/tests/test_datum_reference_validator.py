"""
Test suite: GDT-DATUM-REFERENCE-VALIDATOR
ASME Y14.5-2018 §4.11 datum precedence rules.

Oracle sources (figure-derived cases):
  Fig. 4-1  -- 3-2-1 plane/plane/plane DRF: A (flat_face primary),
               B (flat_face secondary), C (flat_face tertiary) -> VALID
  Fig. 4-2  -- FOS primary: A = cylinder (RMB, modifier S), B = flat_face
               secondary -> VALID; also tests MMB (M) on cylinder -> VALID
  Fig. 4-11 -- Datum target on primary face: 3 point targets -> VALID with
               informational warning about minimum target count

Rule citations tracked per test (ASME Y14.5-2018 §4.11):
  R1  §4.11 / §4.3    -- Missing primary datum
  R5  §4.11           -- Duplicate datum letter
  R6  §4.11.5(a)      -- MMB (M) on planar datum
  R7  §4.11.5(b)      -- LMB (L) on planar datum
  R10 §4.11.5         -- RMB (S) on planar datum
"""

import pytest

from kerf_gdnt.datum_reference_validator import (
    DatumInfo,
    DatumReferenceEntry,
    ValidationReport,
    validate_datum_reference_frame,
    drf_entries_from_datum_refs,
)
from kerf_gdnt.feature_control_frame import DatumReference
from kerf_gdnt.tools import (
    gdt_validate_datum_reference_frame_spec,
    run_gdt_validate_datum_reference_frame,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(label: str, modifier: str = None) -> DatumReferenceEntry:
    return DatumReferenceEntry(label=label, modifier=modifier)


def _flat(label: str) -> DatumInfo:
    return DatumInfo(label=label, feature_type="flat_face")


def _cylinder(label: str) -> DatumInfo:
    return DatumInfo(label=label, feature_type="cylinder")


# ---------------------------------------------------------------------------
# FIGURE 4-1 oracle: valid 3-2-1 plane/plane/plane DRF
# Per ASME Y14.5-2018 Fig. 4-1:
#   A = primary flat face (constrains 3 DOF: Tz, Rx, Ry)
#   B = secondary flat face (constrains 2 DOF: Ty, Rz)
#   C = tertiary flat face (constrains 1 DOF: Tx)
# ---------------------------------------------------------------------------

class TestFigure41_Valid321DRF:
    """Oracle: ASME Y14.5-2018 Fig. 4-1 -- valid 3-2-1 flat-face DRF."""

    def _registry(self) -> dict:
        return {
            "A": _flat("A"),
            "B": _flat("B"),
            "C": _flat("C"),
        }

    def test_valid_3_2_1_no_violations(self):
        """Fig. 4-1: A primary, B secondary, C tertiary -- all flat faces, no modifiers."""
        frame = [_entry("A"), _entry("B"), _entry("C")]
        report = validate_datum_reference_frame(frame, self._registry())
        assert report.valid, f"Expected valid; violations: {report.violations}"
        assert report.violations == []

    def test_valid_primary_only(self):
        """Single primary datum (flat face) -- minimal valid DRF."""
        frame = [_entry("A")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        assert report.valid
        assert report.violations == []

    def test_valid_primary_secondary(self):
        """Two-datum DRF: primary + secondary, no tertiary."""
        frame = [_entry("A"), _entry("B")]
        report = validate_datum_reference_frame(frame, self._registry())
        assert report.valid
        assert report.violations == []


# ---------------------------------------------------------------------------
# FIGURE 4-2 oracle: FOS primary datum (cylinder) with material modifiers
# Per ASME Y14.5-2018 Fig. 4-2:
#   A = cylinder primary datum (RMB -- modifier S)
#   B = flat_face secondary datum (no modifier)
# ---------------------------------------------------------------------------

class TestFigure42_FOSPrimary:
    """Oracle: ASME Y14.5-2018 Fig. 4-2 -- cylindrical primary datum with modifiers."""

    def _registry(self) -> dict:
        return {
            "A": _cylinder("A"),
            "B": _flat("B"),
        }

    def test_valid_rmb_on_cylinder_primary(self):
        """Fig. 4-2: A = cylinder with RMB (S modifier) is valid (§4.11.5)."""
        frame = [_entry("A", modifier="S"), _entry("B")]
        report = validate_datum_reference_frame(frame, self._registry())
        assert report.valid, f"Expected valid; violations: {report.violations}"
        assert not any(v.code == "RMB_ON_PLANAR_DATUM" for v in report.violations)

    def test_valid_mmb_on_cylinder(self):
        """MMB (M) on cylindrical FOS datum is valid (§4.11.5(a))."""
        frame = [_entry("A", modifier="M")]
        report = validate_datum_reference_frame(frame, {"A": _cylinder("A")})
        assert report.valid, f"Expected valid; violations: {report.violations}"

    def test_valid_lmb_on_cylinder(self):
        """LMB (L) on cylindrical FOS datum is valid (§4.11.5(b))."""
        frame = [_entry("A", modifier="L")]
        report = validate_datum_reference_frame(frame, {"A": _cylinder("A")})
        assert report.valid, f"Expected valid; violations: {report.violations}"

    def test_valid_fos_no_modifier_rfs_implied(self):
        """FOS datum without modifier -> RFS implied (§6.3); valid, warning issued."""
        frame = [_entry("A")]
        report = validate_datum_reference_frame(frame, {"A": _cylinder("A")})
        assert report.valid
        # Expect informational warning about implied RFS
        assert any("RFS" in w or "implied" in w.lower() for w in report.warnings)


# ---------------------------------------------------------------------------
# FIGURE 4-11 oracle: datum targets on primary face
# Per ASME Y14.5-2018 Fig. 4-11:
#   A = primary flat face established via 3 point datum targets (A1, A2, A3)
# ---------------------------------------------------------------------------

class TestFigure411_DatumTargets:
    """Oracle: ASME Y14.5-2018 Fig. 4-11 -- datum targets on primary face."""

    def test_valid_point_target_primary(self):
        """Fig. 4-11: Primary flat face with point datum targets -> valid."""
        primary_info = DatumInfo(
            label="A",
            feature_type="flat_face",
            is_datum_target=True,
            target_type="point",
        )
        frame = [_entry("A")]
        report = validate_datum_reference_frame(frame, {"A": primary_info})
        assert report.valid
        # Warning about needing >=3 target points expected
        assert any("3" in w or "three" in w.lower() for w in report.warnings)

    def test_valid_area_target_primary(self):
        """Area datum target on primary flat face -- valid."""
        primary_info = DatumInfo(
            label="A",
            feature_type="flat_face",
            is_datum_target=True,
            target_type="area",
        )
        frame = [_entry("A")]
        report = validate_datum_reference_frame(frame, {"A": primary_info})
        assert report.valid

    def test_valid_line_target_secondary(self):
        """Line datum target on secondary flat face -- valid."""
        frame = [_entry("A"), _entry("B")]
        registry = {
            "A": _flat("A"),
            "B": DatumInfo(
                label="B",
                feature_type="flat_face",
                is_datum_target=True,
                target_type="line",
            ),
        }
        report = validate_datum_reference_frame(frame, registry)
        assert report.valid


# ---------------------------------------------------------------------------
# Violation: missing primary datum (R1 -- §4.11 / §4.3)
# ---------------------------------------------------------------------------

class TestMissingPrimary:
    def test_empty_datum_refs_is_violation(self):
        """No datum references -> MISSING_PRIMARY violation."""
        report = validate_datum_reference_frame([], {})
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "MISSING_PRIMARY" in codes

    def test_missing_primary_rule_citation(self):
        report = validate_datum_reference_frame([], {})
        primary_violation = next(
            v for v in report.violations if v.code == "MISSING_PRIMARY"
        )
        assert "§4.11" in primary_violation.rule or "§4.3" in primary_violation.rule


# ---------------------------------------------------------------------------
# Violation: duplicate datum letter (R5 -- §4.11)
# ---------------------------------------------------------------------------

class TestDuplicateDatumLetter:
    def test_duplicate_primary_secondary(self):
        """Same letter in primary and secondary positions -> DUPLICATE_DATUM_LETTER."""
        frame = [_entry("A"), _entry("A")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "DUPLICATE_DATUM_LETTER" in codes

    def test_duplicate_primary_tertiary(self):
        """Same letter in primary and tertiary -> DUPLICATE_DATUM_LETTER."""
        frame = [_entry("A"), _entry("B"), _entry("A")]
        report = validate_datum_reference_frame(
            frame, {"A": _flat("A"), "B": _flat("B")}
        )
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "DUPLICATE_DATUM_LETTER" in codes

    def test_duplicate_rule_citation(self):
        frame = [_entry("A"), _entry("A")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        dup_violation = next(
            v for v in report.violations if v.code == "DUPLICATE_DATUM_LETTER"
        )
        assert "§4.11" in dup_violation.rule

    def test_no_duplicate_distinct_letters(self):
        frame = [_entry("A"), _entry("B"), _entry("C")]
        report = validate_datum_reference_frame(
            frame,
            {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")},
        )
        codes = [v.code for v in report.violations]
        assert "DUPLICATE_DATUM_LETTER" not in codes


# ---------------------------------------------------------------------------
# Violation: RFS (S modifier) on a planar datum (R10 -- §4.11.5)
# ---------------------------------------------------------------------------

class TestRMBOnPlanarDatum:
    def test_rfs_modifier_on_flat_face_is_violation(self):
        """S (RMB/RFS) modifier on planar datum -> RMB_ON_PLANAR_DATUM violation."""
        frame = [_entry("A", modifier="S")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "RMB_ON_PLANAR_DATUM" in codes

    def test_rfs_on_planar_rule_citation(self):
        frame = [_entry("A", modifier="S")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        violation = next(v for v in report.violations if v.code == "RMB_ON_PLANAR_DATUM")
        assert "§4.11.5" in violation.rule


# ---------------------------------------------------------------------------
# Violation: MMB (M modifier) on a planar datum (R6 -- §4.11.5(a))
# ---------------------------------------------------------------------------

class TestMMBOnPlanarDatum:
    def test_mmb_modifier_on_flat_face_is_violation(self):
        """M (MMB) modifier on a flat-face datum -> MMB_ON_PLANAR_DATUM violation."""
        frame = [_entry("A", modifier="M")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "MMB_ON_PLANAR_DATUM" in codes

    def test_mmb_on_planar_rule_citation(self):
        frame = [_entry("A", modifier="M")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        violation = next(v for v in report.violations if v.code == "MMB_ON_PLANAR_DATUM")
        assert "§4.11.5" in violation.rule or "(a)" in violation.rule

    def test_mmb_secondary_flat_face_violation(self):
        """MMB on secondary flat face also triggers violation."""
        frame = [_entry("A"), _entry("B", modifier="M")]
        report = validate_datum_reference_frame(
            frame, {"A": _flat("A"), "B": _flat("B")}
        )
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "MMB_ON_PLANAR_DATUM" in codes


# ---------------------------------------------------------------------------
# Violation: LMB (L modifier) on a planar datum (R7 -- §4.11.5(b))
# ---------------------------------------------------------------------------

class TestLMBOnPlanarDatum:
    def test_lmb_modifier_on_flat_face_is_violation(self):
        """L (LMB) modifier on a flat-face datum -> LMB_ON_PLANAR_DATUM violation."""
        frame = [_entry("A", modifier="L")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        assert not report.valid
        codes = [v.code for v in report.violations]
        assert "LMB_ON_PLANAR_DATUM" in codes

    def test_lmb_on_planar_rule_citation(self):
        frame = [_entry("A", modifier="L")]
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        violation = next(v for v in report.violations if v.code == "LMB_ON_PLANAR_DATUM")
        assert "§4.11.5" in violation.rule or "(b)" in violation.rule


# ---------------------------------------------------------------------------
# Valid: LMB on feature-of-size -- §4.11.5(b)
# ---------------------------------------------------------------------------

class TestLMBOnFOS:
    def test_lmb_on_slot_datum_is_valid(self):
        """LMB (L) on slot (FOS) datum -> valid per §4.11.5(b)."""
        slot_info = DatumInfo(label="B", feature_type="slot")
        frame = [_entry("A"), _entry("B", modifier="L")]
        report = validate_datum_reference_frame(
            frame, {"A": _flat("A"), "B": slot_info}
        )
        assert report.valid, f"Expected valid; violations: {report.violations}"

    def test_lmb_on_width_datum_is_valid(self):
        """LMB (L) on width (FOS) datum -> valid per §4.11.5(b)."""
        width_info = DatumInfo(label="C", feature_type="width")
        frame = [_entry("A"), _entry("B"), _entry("C", modifier="L")]
        registry = {"A": _flat("A"), "B": _flat("B"), "C": width_info}
        report = validate_datum_reference_frame(frame, registry)
        assert report.valid, f"Expected valid; violations: {report.violations}"

    def test_lmb_on_sphere_is_valid(self):
        """LMB on sphere (FOS) datum -> valid."""
        sphere = DatumInfo(label="A", feature_type="sphere")
        frame = [_entry("A", modifier="L")]
        report = validate_datum_reference_frame(frame, {"A": sphere})
        assert report.valid


# ---------------------------------------------------------------------------
# Composite frame out-of-scope flag (§10.5)
# ---------------------------------------------------------------------------

class TestCompositeFrameFlag:
    def test_composite_lower_segment_skips_drf_checks(self):
        """Composite tolerance frame lower segment -> out-of-scope flag, no violations."""
        frame = [_entry("A"), _entry("A")]  # would be duplicate otherwise
        report = validate_datum_reference_frame(
            frame,
            {"A": _flat("A")},
            is_composite_lower_segment=True,
        )
        assert report.valid
        assert report.composite_scope_flag
        assert report.violations == []
        assert any("§10.5" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Datum reference registry miss -> warning, not error
# ---------------------------------------------------------------------------

class TestUnknownDatumInRegistry:
    def test_unlisted_datum_produces_warning_not_error(self):
        """Datum label referenced but not in registry -> warning only (no violation)."""
        frame = [_entry("A"), _entry("B")]
        # Only A is in the registry
        report = validate_datum_reference_frame(frame, {"A": _flat("A")})
        assert report.valid
        assert any("B" in w for w in report.warnings)


# ---------------------------------------------------------------------------
# Convenience helper: drf_entries_from_datum_refs
# ---------------------------------------------------------------------------

class TestDRFEntriesFromDatumRefs:
    def test_round_trip_from_fcf_datum_refs(self):
        """drf_entries_from_datum_refs correctly wraps FCF DatumReference objects."""
        refs = [
            DatumReference(label="A"),
            DatumReference(label="B", modifier="M"),
            DatumReference(label="C", modifier="L"),
        ]
        entries = drf_entries_from_datum_refs(refs)
        assert entries[0].label == "A"
        assert entries[0].modifier is None
        assert entries[1].label == "B"
        assert entries[1].modifier == "M"
        assert entries[2].label == "C"
        assert entries[2].modifier == "L"


# ---------------------------------------------------------------------------
# LLM tool surface: run_gdt_validate_datum_reference_frame
# ok_payload in the _compat shim serialises the dict directly (no 'ok' wrapper).
# ---------------------------------------------------------------------------

class TestLLMToolSurface:
    def _ctx(self):
        return None

    def _parse(self, result: str) -> dict:
        import json
        payload = json.loads(result)
        # In compat mode ok_payload returns the dict directly; in production
        # it may be wrapped. Support both.
        if "result" in payload:
            return payload["result"]
        return payload

    def test_tool_valid_3_2_1_returns_valid(self):
        """LLM tool: valid 3-2-1 DRF returns valid=True."""
        params = {
            "datum_refs": [
                {"label": "A"},
                {"label": "B"},
                {"label": "C"},
            ],
            "datums": {
                "A": {"feature_type": "flat_face"},
                "B": {"feature_type": "flat_face"},
                "C": {"feature_type": "flat_face"},
            },
        }
        result = run_gdt_validate_datum_reference_frame(params, self._ctx())
        payload = self._parse(result)
        assert payload["valid"] is True
        assert payload["violations"] == []

    def test_tool_missing_primary_returns_violation(self):
        """LLM tool: empty datum_refs -> MISSING_PRIMARY violation in payload."""
        params = {"datum_refs": [], "datums": {}}
        result = run_gdt_validate_datum_reference_frame(params, self._ctx())
        payload = self._parse(result)
        assert payload["valid"] is False
        codes = [v["code"] for v in payload["violations"]]
        assert "MISSING_PRIMARY" in codes

    def test_tool_mmb_on_flat_face_returns_violation(self):
        """LLM tool: MMB on flat-face datum returns MMB_ON_PLANAR_DATUM violation."""
        params = {
            "datum_refs": [{"label": "A", "modifier": "M"}],
            "datums": {"A": {"feature_type": "flat_face"}},
        }
        result = run_gdt_validate_datum_reference_frame(params, self._ctx())
        payload = self._parse(result)
        assert payload["valid"] is False
        codes = [v["code"] for v in payload["violations"]]
        assert "MMB_ON_PLANAR_DATUM" in codes

    def test_tool_lmb_on_cylinder_valid(self):
        """LLM tool: LMB on cylinder FOS datum is valid."""
        params = {
            "datum_refs": [{"label": "A", "modifier": "L"}],
            "datums": {"A": {"feature_type": "cylinder"}},
        }
        result = run_gdt_validate_datum_reference_frame(params, self._ctx())
        payload = self._parse(result)
        assert payload["valid"] is True

    def test_tool_duplicate_datum_returns_violation(self):
        """LLM tool: duplicate datum letter returns DUPLICATE_DATUM_LETTER violation."""
        params = {
            "datum_refs": [{"label": "A"}, {"label": "A"}],
            "datums": {"A": {"feature_type": "flat_face"}},
        }
        result = run_gdt_validate_datum_reference_frame(params, self._ctx())
        payload = self._parse(result)
        assert payload["valid"] is False
        codes = [v["code"] for v in payload["violations"]]
        assert "DUPLICATE_DATUM_LETTER" in codes
