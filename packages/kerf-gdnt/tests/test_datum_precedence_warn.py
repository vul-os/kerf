"""
Test suite: GDT-DATUM-PRECEDENCE-WARN
ASME Y14.5-2018 §4.7 + §4.11 cross-frame datum precedence consistency.

Oracle sources:
  §4.11     — Primary datum establishes highest-priority constraint.
  §4.11.1   — Primary planar: 3 DOF removed.
  §4.7      — Total DOF for rigid body: 6 maximum.
  Fig. 4-1  — Canonical 3-2-1 planar DRF: A primary, B secondary, C tertiary.
  Fig. 4-2  — FOS cylinder primary (RMB) + planar secondary.

Warning codes:
  FEATURE_TYPE_CONFLICT        — P1
  DATUM_USED_AT_MULTIPLE_LEVELS— P1b
  PRECEDENCE_REVERSAL          — P2
  DOF_OVER_CONSTRAINT          — P3
  MODIFIER_CONFLICT            — P4
"""

import json
import pytest

from kerf_gdnt.datum_precedence_warn import (
    DatumFeatureInfo,
    FrameDatumRef,
    FrameSpec,
    PrecedenceReport,
    PrecedenceWarning,
    analyze_datum_precedence_consistency,
)
from kerf_gdnt.tools import (
    gdt_warn_datum_precedence_spec,
    run_gdt_warn_datum_precedence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat(label):
    return DatumFeatureInfo(label=label, feature_type="flat_face")

def _cyl(label):
    return DatumFeatureInfo(label=label, feature_type="cylinder")

def _sphere(label):
    return DatumFeatureInfo(label=label, feature_type="sphere")

def _ref(label, modifier=None):
    return FrameDatumRef(label=label, modifier=modifier)

def _frame(fid, *refs):
    return FrameSpec(frame_id=fid, datum_refs=list(refs))

def _codes(report):
    return {w.code for w in report.warnings}


# ---------------------------------------------------------------------------
# Consistent frames — no warnings
# ---------------------------------------------------------------------------

class TestConsistentFrames:
    def test_three_frames_same_abc_order(self):
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B"), _ref("C")),
            _frame("F2", _ref("A"), _ref("B"), _ref("C")),
            _frame("F3", _ref("A"), _ref("B"), _ref("C")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent, f"Unexpected warnings: {report.warnings}"
        assert report.frames_analysed == 3

    def test_single_frame_no_warnings(self):
        datums = {"A": _flat("A")}
        frames = [_frame("F1", _ref("A"))]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent

    def test_two_frames_different_datums_no_overlap(self):
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C"), "D": _flat("D")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("C"), _ref("D")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent

    def test_empty_frames_list(self):
        report = analyze_datum_precedence_consistency([], {})
        assert report.consistent
        assert report.frames_analysed == 0

    def test_two_frames_abc_consistent_with_modifiers(self):
        datums = {"A": _flat("A"), "B": _cyl("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "M"), _ref("C")),
            _frame("F2", _ref("A"), _ref("B", "M"), _ref("C")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent

    def test_subset_reference_no_reversal(self):
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B"), _ref("C")),
            _frame("F2", _ref("A"), _ref("B")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent


# ---------------------------------------------------------------------------
# P2: Precedence reversal
# ---------------------------------------------------------------------------

class TestPrecedenceReversal:
    def test_ab_to_ba_reversal(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "PRECEDENCE_REVERSAL" in _codes(report)
        w = next(w for w in report.warnings if w.code == "PRECEDENCE_REVERSAL")
        assert "F1" in w.affected_frames
        assert "F2" in w.affected_frames
        assert w.severity == "WARNING"
        assert "swapped" in w.message

    def test_abc_to_bac_reversal(self):
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B"), _ref("C")),
            _frame("F2", _ref("B"), _ref("A"), _ref("C")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "PRECEDENCE_REVERSAL" in _codes(report)
        reversal_warns = [w for w in report.warnings if w.code == "PRECEDENCE_REVERSAL"]
        assert any("A" in w.message and "B" in w.message for w in reversal_warns)

    def test_rule_citation_is_4_11(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        w = next(w for w in report.warnings if w.code == "PRECEDENCE_REVERSAL")
        assert "§4.11" in w.rule

    def test_three_frames_two_reversals(self):
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B"), _ref("C")),
            _frame("F2", _ref("B"), _ref("A"), _ref("C")),
            _frame("F3", _ref("C"), _ref("A"), _ref("B")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        reversal_warns = [w for w in report.warnings if w.code == "PRECEDENCE_REVERSAL"]
        assert len(reversal_warns) >= 2

    def test_precedence_reversal_has_recommendation(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        w = next(w for w in report.warnings if w.code == "PRECEDENCE_REVERSAL")
        assert w.recommendation.strip() != ""


# ---------------------------------------------------------------------------
# P1: Feature-type / multi-level
# ---------------------------------------------------------------------------

class TestFeatureTypeConflict:
    def test_primary_a_planar_vs_cylindrical(self):
        datums = {"A": _cyl("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "DATUM_USED_AT_MULTIPLE_LEVELS" in _codes(report)
        assert "PRECEDENCE_REVERSAL" in _codes(report)

    def test_datum_used_at_multiple_levels_warning(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        multi_warns = [w for w in report.warnings if w.code == "DATUM_USED_AT_MULTIPLE_LEVELS"]
        assert len(multi_warns) >= 1
        assert any(w.datum_label == "A" for w in multi_warns)

    def test_datum_multiple_levels_severity_is_warning(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        multi_warns = [w for w in report.warnings if w.code == "DATUM_USED_AT_MULTIPLE_LEVELS"]
        assert all(w.severity == "WARNING" for w in multi_warns)

    def test_same_datum_same_position_same_type_no_conflict(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("A"), _ref("B")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "FEATURE_TYPE_CONFLICT" not in _codes(report)
        assert report.consistent


# ---------------------------------------------------------------------------
# P3: DOF inconsistency
# ---------------------------------------------------------------------------

class TestDOFInconsistency:
    def test_valid_3_2_1_no_dof_error(self):
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [_frame("F1", _ref("A"), _ref("B"), _ref("C"))]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "DOF_OVER_CONSTRAINT" not in _codes(report)

    def test_sphere_plus_two_planar_exactly_6(self):
        datums = {"A": _sphere("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [_frame("F1", _ref("A"), _ref("B"), _ref("C"))]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "DOF_OVER_CONSTRAINT" not in _codes(report)

    def test_cylinder_primary_no_over_constraint(self):
        datums = {"A": _cyl("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [_frame("F1", _ref("A"), _ref("B"), _ref("C"))]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "DOF_OVER_CONSTRAINT" not in _codes(report)

    def test_dof_error_severity_is_error(self):
        import kerf_gdnt.datum_precedence_warn as _m
        orig = dict(_m._DOF_REMOVED)
        try:
            _m._DOF_REMOVED[("sphere", 0)] = 4
            datums = {"A": _sphere("A"), "B": _flat("B"), "C": _flat("C")}
            frames = [_frame("F1", _ref("A"), _ref("B"), _ref("C"))]
            report = analyze_datum_precedence_consistency(frames, datums)
            dof_warns = [w for w in report.warnings if w.code == "DOF_OVER_CONSTRAINT"]
            assert len(dof_warns) == 1
            assert dof_warns[0].severity == "ERROR"
            assert "§4.7" in dof_warns[0].rule
        finally:
            _m._DOF_REMOVED.clear()
            _m._DOF_REMOVED.update(orig)

    def test_dof_over_constraint_has_recommendation(self):
        import kerf_gdnt.datum_precedence_warn as _m
        orig = dict(_m._DOF_REMOVED)
        try:
            _m._DOF_REMOVED[("sphere", 0)] = 4
            datums = {"A": _sphere("A"), "B": _flat("B"), "C": _flat("C")}
            frames = [_frame("F1", _ref("A"), _ref("B"), _ref("C"))]
            report = analyze_datum_precedence_consistency(frames, datums)
            dof_warns = [w for w in report.warnings if w.code == "DOF_OVER_CONSTRAINT"]
            assert dof_warns[0].recommendation.strip() != ""
        finally:
            _m._DOF_REMOVED.clear()
            _m._DOF_REMOVED.update(orig)


# ---------------------------------------------------------------------------
# P4: Modifier conflict
# ---------------------------------------------------------------------------

class TestModifierConflict:
    def test_same_modifier_no_conflict(self):
        datums = {"A": _flat("A"), "B": _cyl("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "M")),
            _frame("F2", _ref("A"), _ref("B", "M")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "MODIFIER_CONFLICT" not in _codes(report)

    def test_rmb_vs_mmb_conflict(self):
        datums = {"A": _flat("A"), "B": _cyl("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "S")),
            _frame("F2", _ref("A"), _ref("B", "M")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "MODIFIER_CONFLICT" in _codes(report)
        w = next(w for w in report.warnings if w.code == "MODIFIER_CONFLICT")
        assert w.datum_label == "B"
        assert w.severity == "WARNING"
        assert "§4.11.5" in w.rule

    def test_mmb_vs_lmb_conflict(self):
        datums = {"A": _flat("A"), "B": _cyl("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "M")),
            _frame("F2", _ref("A"), _ref("B", "L")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "MODIFIER_CONFLICT" in _codes(report)

    def test_none_vs_explicit_modifier_conflict(self):
        datums = {"A": _flat("A"), "B": _cyl("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("A"), _ref("B", "M")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "MODIFIER_CONFLICT" in _codes(report)

    def test_modifier_conflict_has_recommendation(self):
        datums = {"A": _flat("A"), "B": _cyl("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "S")),
            _frame("F2", _ref("A"), _ref("B", "M")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        w = next(w for w in report.warnings if w.code == "MODIFIER_CONFLICT")
        assert w.recommendation.strip() != ""

    def test_modifier_conflict_all_affected_frames_listed(self):
        datums = {"A": _flat("A"), "B": _cyl("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "S")),
            _frame("F2", _ref("A"), _ref("B", "M")),
            _frame("F3", _ref("A"), _ref("B", "L")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        w = next(w for w in report.warnings if w.code == "MODIFIER_CONFLICT")
        assert set(w.affected_frames) == {"F1", "F2", "F3"}


# ---------------------------------------------------------------------------
# ASME Y14.5 oracle examples
# ---------------------------------------------------------------------------

class TestASMEOracles:
    def test_oracle_fig4_1_three_consistent_frames(self):
        """Fig. 4-1: three frames all A|B|C planar → consistent, no warnings."""
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [
            _frame("position_F1", _ref("A"), _ref("B"), _ref("C")),
            _frame("perpendicularity_F2", _ref("A"), _ref("B"), _ref("C")),
            _frame("profile_F3", _ref("A"), _ref("B"), _ref("C")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent
        assert len(report.warnings) == 0

    def test_oracle_fig4_2_fos_primary_consistent(self):
        """Fig. 4-2: two frames cylinder primary A (S) + planar secondary B → consistent."""
        datums = {"A": _cyl("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A", "S"), _ref("B")),
            _frame("F2", _ref("A", "S"), _ref("B")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent

    def test_oracle_section_4_11_reversal(self):
        """§4.11 text: frame1=A|B|C, frame2=B|A|C → PRECEDENCE_REVERSAL."""
        datums = {"A": _flat("A"), "B": _flat("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B"), _ref("C")),
            _frame("F2", _ref("B"), _ref("A"), _ref("C")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "PRECEDENCE_REVERSAL" in _codes(report)
        w = next(w for w in report.warnings if w.code == "PRECEDENCE_REVERSAL")
        assert "F1" in w.affected_frames and "F2" in w.affected_frames
        assert "A" in w.message and "B" in w.message

    def test_oracle_modifier_rmb_vs_mmb_same_datum(self):
        """§4.11.5: A used as RMB (S) in one frame and MMB (M) in another."""
        datums = {"A": _cyl("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A", "S"), _ref("B")),
            _frame("F2", _ref("A", "M"), _ref("B")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert "MODIFIER_CONFLICT" in _codes(report)
        w = next(w for w in report.warnings if w.code == "MODIFIER_CONFLICT")
        assert w.datum_label == "A"

    def test_oracle_combined_reversal_and_modifier_conflict(self):
        """Combined: frame1=A|B(M)|C, frame2=B(L)|A|C → both PRECEDENCE_REVERSAL and MODIFIER_CONFLICT."""
        datums = {"A": _flat("A"), "B": _cyl("B"), "C": _flat("C")}
        frames = [
            _frame("F1", _ref("A"), _ref("B", "M"), _ref("C")),
            _frame("F2", _ref("B", "L"), _ref("A"), _ref("C")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        codes = _codes(report)
        assert "PRECEDENCE_REVERSAL" in codes
        assert "MODIFIER_CONFLICT" in codes


# ---------------------------------------------------------------------------
# Report structure
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_to_dict_keys(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [_frame("F1", _ref("A"), _ref("B"))]
        report = analyze_datum_precedence_consistency(frames, datums)
        d = report.to_dict()
        for key in ("consistent", "warning_count", "warnings", "recommendations", "frames_analysed"):
            assert key in d

    def test_warning_to_dict_keys(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        for w in report.warnings:
            d = w.to_dict()
            for key in ("code", "severity", "message", "rule", "affected_frames",
                        "datum_label", "recommendation"):
                assert key in d

    def test_consistent_true_when_no_warnings(self):
        datums = {"A": _flat("A")}
        frames = [_frame("F1", _ref("A"))]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent is True

    def test_consistent_false_when_warnings_present(self):
        datums = {"A": _flat("A"), "B": _flat("B")}
        frames = [
            _frame("F1", _ref("A"), _ref("B")),
            _frame("F2", _ref("B"), _ref("A")),
        ]
        report = analyze_datum_precedence_consistency(frames, datums)
        assert report.consistent is False


# ---------------------------------------------------------------------------
# LLM tool surface
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_spec_has_required_fields(self):
        assert gdt_warn_datum_precedence_spec.name == "gdt_warn_datum_precedence"
        assert "§4.7" in gdt_warn_datum_precedence_spec.description
        assert "§4.11" in gdt_warn_datum_precedence_spec.description
        assert "HONEST FLAG" in gdt_warn_datum_precedence_spec.description

    def test_run_consistent_frames(self):
        params = {
            "frames": [
                {"frame_id": "F1", "datum_refs": [{"label": "A"}, {"label": "B"}, {"label": "C"}]},
                {"frame_id": "F2", "datum_refs": [{"label": "A"}, {"label": "B"}, {"label": "C"}]},
            ],
            "datums": {
                "A": {"feature_type": "flat_face"},
                "B": {"feature_type": "flat_face"},
                "C": {"feature_type": "flat_face"},
            },
        }
        result = json.loads(run_gdt_warn_datum_precedence(params, None))
        assert result["consistent"] is True
        assert result["warning_count"] == 0

    def test_run_precedence_reversal(self):
        params = {
            "frames": [
                {"frame_id": "F1", "datum_refs": [{"label": "A"}, {"label": "B"}]},
                {"frame_id": "F2", "datum_refs": [{"label": "B"}, {"label": "A"}]},
            ],
            "datums": {
                "A": {"feature_type": "flat_face"},
                "B": {"feature_type": "flat_face"},
            },
        }
        result = json.loads(run_gdt_warn_datum_precedence(params, None))
        assert result["consistent"] is False
        codes = {w["code"] for w in result["warnings"]}
        assert "PRECEDENCE_REVERSAL" in codes

    def test_run_modifier_conflict(self):
        params = {
            "frames": [
                {"frame_id": "F1", "datum_refs": [{"label": "A"}, {"label": "B", "modifier": "M"}]},
                {"frame_id": "F2", "datum_refs": [{"label": "A"}, {"label": "B", "modifier": "L"}]},
            ],
            "datums": {
                "A": {"feature_type": "flat_face"},
                "B": {"feature_type": "cylinder"},
            },
        }
        result = json.loads(run_gdt_warn_datum_precedence(params, None))
        assert result["consistent"] is False
        codes = {w["code"] for w in result["warnings"]}
        assert "MODIFIER_CONFLICT" in codes

    def test_run_error_handling(self):
        result = json.loads(run_gdt_warn_datum_precedence({}, None))
        assert "consistent" in result or "error" in result

    def test_run_returns_json_string(self):
        params = {
            "frames": [{"frame_id": "F1", "datum_refs": [{"label": "A"}]}],
            "datums": {"A": {"feature_type": "flat_face"}},
        }
        result = run_gdt_warn_datum_precedence(params, None)
        assert isinstance(result, str)
        assert isinstance(json.loads(result), dict)
