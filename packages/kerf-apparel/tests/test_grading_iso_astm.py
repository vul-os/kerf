"""
Tests for ASTM D5219 + ISO 8559-2 industry-standard grading rules.

Oracles
-------
1. Standard increment (ASTM D5219-09, Table 1 — US misses):
   women_us 4→6: chest_girth delta = 25 mm; waist_girth = 25 mm; hip_girth = 25 mm.

2. Grade pattern roundtrip:
   A bodice_front graded from size 4 to size 6 (women_us spec) gains
   grade_dx_mm = 6.25 mm per quarter-block, meaning full bust girth
   increases by 4 × 6.25 = 25 mm.

3. Non-standard code warning:
   grade_check_iso_8559({"neck_left": 38.0}) → one GradingWarning returned;
   "neck_left" is not in ISO 8559-2:2017 canonical codes.

4. EU vs US increment:
   women_eu 36→38: chest_girth delta = 40 mm (ISO 8559-2:2017 Annex A,
   Table A.1 — 4 cm per EU step), different from US 25 mm.
"""

from __future__ import annotations

import pytest

from kerf_apparel.grading import (
    GradingRule,
    GradingWarning,
    build_grading_table,
    apply_grading,
    grade_check_iso_8559,
)
from kerf_apparel.blocks import bodice_front, get_measurements


# ------------------------------------------------------------------ #
# 1. Standard increment — ASTM D5219-09 Table 1 (women_us)            #
# ------------------------------------------------------------------ #

class TestStandardIncrementWomenUS:
    """ASTM D5219-09 Table 1 oracle: US misses women 4→6."""

    @pytest.fixture(scope="class")
    def table(self):
        return build_grading_table(spec="women_us")

    def test_chest_girth_4_to_6_is_25mm(self, table):
        """ASTM D5219-09 Table 1: chest/bust increment = 25 mm per grade step."""
        rules = [
            r for r in table
            if r.measurement_code == "chest_girth"
            and r.from_size == "4"
            and r.to_size == "6"
        ]
        assert len(rules) == 1, "Expected exactly one chest_girth rule for 4→6"
        assert rules[0].delta_mm == pytest.approx(25.0), (
            f"chest_girth 4→6 delta = {rules[0].delta_mm} mm, expected 25 mm "
            "(ASTM D5219-09 Table 1)"
        )

    def test_waist_girth_4_to_6_is_25mm(self, table):
        """ASTM D5219-09 Table 1: waist increment = 25 mm per grade step."""
        rules = [
            r for r in table
            if r.measurement_code == "waist_girth"
            and r.from_size == "4"
            and r.to_size == "6"
        ]
        assert len(rules) == 1
        assert rules[0].delta_mm == pytest.approx(25.0), (
            f"waist_girth 4→6 delta = {rules[0].delta_mm} mm, expected 25 mm"
        )

    def test_hip_girth_4_to_6_is_25mm(self, table):
        """ASTM D5219-09 Table 1: hip increment = 25 mm per grade step."""
        rules = [
            r for r in table
            if r.measurement_code == "hip_girth"
            and r.from_size == "4"
            and r.to_size == "6"
        ]
        assert len(rules) == 1
        assert rules[0].delta_mm == pytest.approx(25.0), (
            f"hip_girth 4→6 delta = {rules[0].delta_mm} mm, expected 25 mm"
        )

    def test_rule_spec_label(self, table):
        """Every rule in a women_us table should have spec='women_us'."""
        for r in table:
            assert r.spec == "women_us", f"Expected spec='women_us', got {r.spec!r}"

    def test_grading_rule_is_dataclass(self, table):
        """GradingRule instances have the required fields."""
        r = table[0]
        assert isinstance(r, GradingRule)
        assert hasattr(r, "from_size")
        assert hasattr(r, "to_size")
        assert hasattr(r, "measurement_code")
        assert hasattr(r, "delta_mm")
        assert hasattr(r, "spec")

    def test_table_covers_full_size_run(self, table):
        """Table should include rules from size 0 through 22 (11 steps)."""
        from_sizes = {r.from_size for r in table}
        # Expect steps 0→2, 2→4, ..., 20→22
        expected_starts = {"0", "2", "4", "6", "8", "10", "12", "14", "16", "18", "20"}
        assert expected_starts.issubset(from_sizes)

    def test_delta_is_positive_for_size_up(self, table):
        """All deltas in the table should be positive (size going up)."""
        for r in table:
            assert r.delta_mm > 0, (
                f"Expected positive delta for {r.from_size}→{r.to_size} "
                f"({r.measurement_code}), got {r.delta_mm}"
            )


# ------------------------------------------------------------------ #
# 2. Grade pattern roundtrip                                           #
# ------------------------------------------------------------------ #

class TestGradePatternRoundtrip:
    """
    Oracle: bodice_front size 4 → size 6 (women_us).
    Full bust girth increase = 4 × grade_dx_mm = 25 mm.
    """

    @pytest.fixture(scope="class")
    def graded(self):
        m4 = get_measurements("4")
        piece4 = bodice_front(m4["bust"], m4["waist"], m4["hip"], m4["back_length"])
        table = build_grading_table(spec="women_us")
        return apply_grading(piece4, "4", "6", table, spec="women_us")

    @pytest.fixture(scope="class")
    def piece4(self):
        m4 = get_measurements("4")
        return bodice_front(m4["bust"], m4["waist"], m4["hip"], m4["back_length"])

    def test_full_bust_girth_increase_is_25mm(self, graded):
        """
        grade_dx_mm is the per-quarter-block shift; full girth = grade_dx_mm × 4 = 25 mm.
        Reference: ASTM D5219-09 Table 1 — chest increment 25 mm per grade step.
        """
        dx_mm = graded.labels.get("grade_dx_mm", 0.0)
        full_girth_increase = dx_mm * 4  # 4 quarter-blocks
        assert full_girth_increase == pytest.approx(25.0, abs=0.01), (
            f"Full bust girth increase = {full_girth_increase:.3f} mm, "
            "expected 25 mm (ASTM D5219-09)"
        )

    def test_graded_piece_is_wider(self, graded, piece4):
        """Graded piece should be wider than the source piece."""
        bb4 = piece4.bounding_box()
        bb6 = graded.bounding_box()
        w4 = bb4[2] - bb4[0]
        w6 = bb6[2] - bb6[0]
        assert w6 > w4, f"Graded width {w6:.3f} cm not wider than source {w4:.3f} cm"

    def test_graded_labels_contain_size_info(self, graded):
        """Graded piece labels must record from_size and to_size."""
        assert graded.labels["from_size"] == "4"
        assert graded.labels["to_size"] == "6"

    def test_grade_dx_mm_is_6_25(self, graded):
        """Each quarter-block shift = 25 mm / 4 = 6.25 mm."""
        dx = graded.labels.get("grade_dx_mm", 0.0)
        assert dx == pytest.approx(6.25, abs=0.01), (
            f"grade_dx_mm = {dx:.3f} mm, expected 6.25 mm"
        )

    def test_graded_piece_is_patternpiece(self, graded):
        from kerf_apparel.blocks import PatternPiece
        assert isinstance(graded, PatternPiece)

    def test_graded_outline_is_closed(self, graded):
        assert graded.outline[0] == graded.outline[-1]

    def test_same_size_roundtrip_is_identity(self):
        """Grading from_size == to_size must return a copy of the same piece."""
        m4 = get_measurements("4")
        piece = bodice_front(m4["bust"], m4["waist"], m4["hip"], m4["back_length"])
        table = build_grading_table(spec="women_us")
        same = apply_grading(piece, "4", "4", table, spec="women_us")
        bb_orig = piece.bounding_box()
        bb_same = same.bounding_box()
        for a, b in zip(bb_orig, bb_same):
            assert a == pytest.approx(b, abs=1e-9)


# ------------------------------------------------------------------ #
# 3. Non-standard code warning                                         #
# ------------------------------------------------------------------ #

class TestGradeCheckISO8559:
    """Oracle: grade_check_iso_8559 flags non-standard measurement codes."""

    def test_non_standard_code_returns_warning(self):
        """
        'neck_left' is not in ISO 8559-2:2017 canonical code table.
        grade_check_iso_8559 must return exactly one warning.
        """
        warnings = grade_check_iso_8559({"neck_left": 38.0})
        assert len(warnings) == 1, (
            f"Expected 1 warning for 'neck_left', got {len(warnings)}"
        )
        assert warnings[0].code == "neck_left"

    def test_warning_message_mentions_iso(self):
        """Warning message should reference ISO 8559-2."""
        warnings = grade_check_iso_8559({"neck_left": 38.0})
        assert "ISO 8559" in warnings[0].message, (
            f"Warning message should mention ISO 8559-2, got: {warnings[0].message!r}"
        )

    def test_standard_codes_return_no_warnings(self):
        """All standard ISO 8559-2 codes must pass validation cleanly."""
        measurements = {
            "chest_girth": 92.0,
            "waist_girth": 74.0,
            "hip_girth": 98.0,
        }
        warnings = grade_check_iso_8559(measurements)
        assert warnings == [], (
            f"Expected no warnings for standard codes, got: {warnings}"
        )

    def test_mixed_codes_flags_non_standard_only(self):
        """Only non-standard codes get warnings; standard ones pass silently."""
        measurements = {
            "chest_girth": 92.0,      # standard
            "neck_left": 38.0,        # non-standard
            "custom_metric_v2": 10.0, # non-standard
        }
        warnings = grade_check_iso_8559(measurements)
        flagged = {w.code for w in warnings}
        assert "neck_left" in flagged
        assert "custom_metric_v2" in flagged
        assert "chest_girth" not in flagged, (
            "'chest_girth' is ISO 8559-2 standard — should not be flagged"
        )

    def test_empty_dict_returns_no_warnings(self):
        assert grade_check_iso_8559({}) == []

    def test_warning_is_grading_warning_dataclass(self):
        warnings = grade_check_iso_8559({"bad_code": 1.0})
        assert isinstance(warnings[0], GradingWarning)
        assert hasattr(warnings[0], "code")
        assert hasattr(warnings[0], "message")


# ------------------------------------------------------------------ #
# 4. EU vs US increment difference                                     #
# ------------------------------------------------------------------ #

class TestEUvsUSIncrement:
    """
    Oracle: women_eu 36→38 chest_girth delta = 40 mm.
    ISO 8559-2:2017 Annex A, Table A.1: European size designation —
    4 cm circumference increment per size step (40 mm), different from
    US ASTM D5219 25 mm.
    """

    @pytest.fixture(scope="class")
    def eu_table(self):
        return build_grading_table(spec="women_eu")

    @pytest.fixture(scope="class")
    def us_table(self):
        return build_grading_table(spec="women_us")

    def test_eu_chest_36_to_38_is_40mm(self, eu_table):
        """ISO 8559-2:2017 Annex A: EU chest increment = 40 mm per step."""
        rules = [
            r for r in eu_table
            if r.measurement_code == "chest_girth"
            and r.from_size == "36"
            and r.to_size == "38"
        ]
        assert len(rules) == 1, "Expected exactly one chest_girth rule for EU 36→38"
        assert rules[0].delta_mm == pytest.approx(40.0), (
            f"EU chest_girth 36→38 delta = {rules[0].delta_mm} mm, "
            "expected 40 mm (ISO 8559-2:2017 Annex A)"
        )

    def test_eu_increment_differs_from_us(self, eu_table, us_table):
        """EU chest increment (40 mm) must differ from US chest increment (25 mm)."""
        eu_chest = next(
            r.delta_mm for r in eu_table
            if r.measurement_code == "chest_girth" and r.from_size == "36"
        )
        us_chest = next(
            r.delta_mm for r in us_table
            if r.measurement_code == "chest_girth" and r.from_size == "4"
        )
        assert eu_chest != us_chest, (
            f"EU and US increments should differ: EU={eu_chest} mm, US={us_chest} mm"
        )
        assert eu_chest > us_chest, (
            f"EU increment ({eu_chest} mm) should be larger than US ({us_chest} mm)"
        )

    def test_eu_table_spec_label(self, eu_table):
        for r in eu_table:
            assert r.spec == "women_eu"

    def test_men_us_chest_is_30mm(self):
        """ASTM D5219-09 Table 2: men's US chest increment = 30 mm."""
        table = build_grading_table(spec="men_us")
        rules = [r for r in table if r.measurement_code == "chest_girth"]
        assert all(r.delta_mm == pytest.approx(30.0) for r in rules), (
            "All men_us chest_girth deltas should be 30 mm"
        )

    def test_build_grading_table_invalid_spec_raises(self):
        with pytest.raises(ValueError, match="Unknown spec"):
            build_grading_table(spec="invalid_spec")

    def test_build_grading_table_too_short_size_range_raises(self):
        with pytest.raises(ValueError, match="at least 2"):
            build_grading_table(spec="women_us", size_range=["4"])
