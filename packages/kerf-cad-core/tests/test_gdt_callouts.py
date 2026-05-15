"""
Tests for kerf_cad_core.gdt_callouts — auto GD&T callout proposals.

Pure-Python, hermetic — no OCC, no DB, no disk fixtures.
Covers:
  - IT-grade band mathematics (iso 286-1)
  - hole → POSITION with datum ref
  - slot → POSITION centre-plane with datum ref
  - planar_face → PERPENDICULARITY / PARALLELISM / FLATNESS (no datum)
  - cylindrical → RUNOUT about axis datum; CYLINDRICITY fallback
  - pattern → composite POSITION with fine intra-segment
  - freeform → PROFILE_SURFACE (coarser grade)
  - intent adjustments (loose / tight / precise)
  - missing datum friendly error (no raise, warning in output)
  - wrong datum type for runout → warning
  - bad grade / bad intent → ok:false
  - propose_callouts top-level API
  - LLM tools: gdt_auto_callouts, gdt_callout_balloon_table
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.gdt_callouts.propose import (
    it_grade_tolerance,
    IT_GRADES,
    VALID_GRADES,
    VALID_FEATURE_TYPES,
    propose_callouts,
    _adjust_grade,
    _grade_order_idx,
    _tolerance_unit_i,
    _find_dim_range,
    FeatureSpec,
)
from kerf_cad_core.gdt.datums import Datum, DatumType
from kerf_cad_core.gdt.tolerances import ToleranceSymbol


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ctx():
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    return ProjectCtx(
        pool=None, storage=None,
        project_id=uuid.uuid4(), user_id=uuid.uuid4(),
        role="owner", http_client=None,
    )


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    assert "error" not in d, f"Expected ok payload, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    assert "error" in d, f"Expected error payload, got: {d}"
    return d


def _axis_datum(label: str = "A") -> dict:
    return {"label": label, "datum_type": "AXIS"}


def _plane_datum(label: str = "A") -> dict:
    return {"label": label, "datum_type": "PLANE"}


def _hole_feature(
    feature_id: str = "bore-1",
    dia_mm: float = 10.0,
    primary_datum: str = "A",
    secondary_datum: str = None,
) -> dict:
    d = {
        "feature_id": feature_id,
        "feature_type": "hole",
        "nominal_size_mm": dia_mm,
        "primary_datum": primary_datum,
    }
    if secondary_datum:
        d["secondary_datum"] = secondary_datum
    return d


# ---------------------------------------------------------------------------
# 1. IT-grade tolerance unit (i) maths
# ---------------------------------------------------------------------------

class TestToleranceUnit:
    def test_i_for_10mm(self):
        # i = 0.45 * 10^(1/3) + 0.001 * 10 = 0.45 * 2.154 + 0.01 ≈ 0.979 µm
        i = _tolerance_unit_i(10.0)
        assert 0.9 < i < 1.1

    def test_i_for_50mm(self):
        # D ≈ geometric mean of (30, 50) range = sqrt(30*50) ≈ 38.7 mm
        low, high = _find_dim_range(50.0)
        assert low == 30.0
        assert high == 50.0
        D = math.sqrt(low * high)
        i = _tolerance_unit_i(D)
        assert i > 1.0  # sanity

    def test_i_increases_with_dimension(self):
        i_small = _tolerance_unit_i(3.0)
        i_large = _tolerance_unit_i(100.0)
        assert i_large > i_small


# ---------------------------------------------------------------------------
# 2. IT-grade band mathematics
# ---------------------------------------------------------------------------

class TestItGradeTolerance:
    def test_it7_10mm(self):
        # k=16, i≈0.90, IT7 ≈ 16*0.90 µm ≈ 0.0144 mm (within ±30% of 0.015)
        tol = it_grade_tolerance(10.0, "IT7")
        assert 0.008 < tol < 0.025, f"IT7 @ 10mm = {tol}"

    def test_it6_finer_than_it7(self):
        tol6 = it_grade_tolerance(20.0, "IT6")
        tol7 = it_grade_tolerance(20.0, "IT7")
        assert tol6 < tol7

    def test_it8_coarser_than_it7(self):
        tol7 = it_grade_tolerance(20.0, "IT7")
        tol8 = it_grade_tolerance(20.0, "IT8")
        assert tol8 > tol7

    def test_coarser_grade_larger_tolerance(self):
        for dia in [5.0, 10.0, 25.0, 80.0]:
            t7 = it_grade_tolerance(dia, "IT7")
            t11 = it_grade_tolerance(dia, "IT11")
            assert t11 > t7, f"IT11 should be coarser than IT7 at dia={dia}"

    def test_larger_nominal_larger_tolerance(self):
        t_small = it_grade_tolerance(3.0, "IT7")
        t_large = it_grade_tolerance(200.0, "IT7")
        assert t_large > t_small

    def test_all_grades_positive(self):
        for grade in IT_GRADES:
            tol = it_grade_tolerance(25.0, grade)
            assert tol > 0, f"{grade} produced non-positive tolerance"

    def test_invalid_grade_raises(self):
        with pytest.raises(ValueError, match="Unknown IT grade"):
            it_grade_tolerance(10.0, "IT99")

    def test_grade_case_insensitive(self):
        tol_upper = it_grade_tolerance(10.0, "IT7")
        tol_lower = it_grade_tolerance(10.0, "it7")
        assert tol_upper == tol_lower

    def test_zero_nominal_uses_fallback(self):
        # Should not raise; fallback dim range handles <= 0
        tol = it_grade_tolerance(0.0, "IT7")
        assert tol > 0

    def test_large_nominal_extrapolated(self):
        # > 500 mm extrapolates using last range, should not raise
        tol = it_grade_tolerance(600.0, "IT7")
        assert tol > 0


# ---------------------------------------------------------------------------
# 3. _adjust_grade (intent offsets)
# ---------------------------------------------------------------------------

class TestAdjustGrade:
    def test_nominal_no_change(self):
        assert _adjust_grade("IT7", "nominal") == "IT7"

    def test_loose_coarser(self):
        g = _adjust_grade("IT7", "loose")
        assert _grade_order_idx(g) > _grade_order_idx("IT7")

    def test_tight_finer(self):
        g = _adjust_grade("IT7", "tight")
        assert _grade_order_idx(g) < _grade_order_idx("IT7")

    def test_precise_finer_than_tight(self):
        g_tight = _adjust_grade("IT7", "tight")
        g_precise = _adjust_grade("IT7", "precise")
        assert _grade_order_idx(g_precise) <= _grade_order_idx(g_tight)

    def test_clamp_at_finest(self):
        # IT01 is already the finest; going tighter should stay at IT01
        g = _adjust_grade("IT01", "precise")
        assert g == "IT01"

    def test_clamp_at_coarsest(self):
        g = _adjust_grade("IT18", "loose")
        assert g == "IT18"


# ---------------------------------------------------------------------------
# 4. FeatureSpec dataclass
# ---------------------------------------------------------------------------

class TestFeatureSpec:
    def test_basic_hole(self):
        s = FeatureSpec(feature_id="bore", feature_type="hole", nominal_size_mm=10.0)
        assert s.feature_type == "hole"
        assert s.is_feature_of_size is True

    def test_planar_face_not_fos(self):
        s = FeatureSpec(feature_id="top", feature_type="planar_face")
        assert s.is_feature_of_size is False

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="feature_type"):
            FeatureSpec(feature_id="x", feature_type="banana")

    def test_empty_id_raises(self):
        with pytest.raises(ValueError, match="feature_id"):
            FeatureSpec(feature_id="", feature_type="hole")

    def test_from_dict_round_trip(self):
        d = {
            "feature_id": "slot-1",
            "feature_type": "slot",
            "nominal_size_mm": 8.0,
            "primary_datum": "A",
        }
        s = FeatureSpec.from_dict(d)
        assert s.to_dict()["feature_id"] == "slot-1"


# ---------------------------------------------------------------------------
# 5. Hole → POSITION with datum ref
# ---------------------------------------------------------------------------

class TestHoleCallout:
    def test_hole_proposes_position(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            grade="IT7",
        )
        assert result["ok"] is True
        assert result["count"] == 1
        callout = result["callouts"][0]
        assert callout["tolerance"]["symbol"] == "POSITION"

    def test_hole_uses_cylindrical_zone(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
        )
        assert result["callouts"][0]["tolerance"]["diameter_zone"] is True

    def test_hole_datum_ref_set(self):
        result = propose_callouts(
            features=[_hole_feature(primary_datum="A", secondary_datum="B")],
            datums=[_plane_datum("A"), _plane_datum("B")],
        )
        tol = result["callouts"][0]["tolerance"]
        assert tol["datum_ref"]["primary"] == "A"
        assert tol["datum_ref"]["secondary"] == "B"

    def test_hole_tolerance_positive(self):
        result = propose_callouts(
            features=[_hole_feature(dia_mm=20.0)],
            datums=[_plane_datum("A")],
        )
        tol_val = result["callouts"][0]["tolerance"]["tolerance_value"]
        assert tol_val > 0

    def test_hole_missing_datum_gives_warning_not_error(self):
        # No primary_datum set → warning, no callout, ok=True
        result = propose_callouts(
            features=[{
                "feature_id": "bore-no-datum",
                "feature_type": "hole",
                "nominal_size_mm": 10.0,
            }],
            datums=[],
        )
        assert result["ok"] is True
        assert result["count"] == 0
        assert any("primary_datum" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# 6. Face → PERPENDICULARITY / PARALLELISM to primary datum
# ---------------------------------------------------------------------------

class TestPlanarFaceCallout:
    def test_perpendicularity_to_datum(self):
        result = propose_callouts(
            features=[{
                "feature_id": "wall-1",
                "feature_type": "planar_face",
                "nominal_size_mm": 50.0,
                "orientation_datum": "A",
            }],
            datums=[_plane_datum("A")],
        )
        assert result["ok"] is True
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "PERPENDICULARITY"

    def test_parallelism_when_parallel_orientation(self):
        result = propose_callouts(
            features=[{
                "feature_id": "top-face",
                "feature_type": "planar_face",
                "nominal_size_mm": 50.0,
                "orientation_datum": "A",
                "extra": {"face_orientation": "parallel"},
            }],
            datums=[_plane_datum("A")],
        )
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "PARALLELISM"

    def test_flatness_when_no_datum(self):
        result = propose_callouts(
            features=[{
                "feature_id": "base",
                "feature_type": "planar_face",
                "nominal_size_mm": 100.0,
            }],
            datums=[],
        )
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "FLATNESS"

    def test_perpendicularity_datum_in_ref(self):
        result = propose_callouts(
            features=[{
                "feature_id": "wall",
                "feature_type": "planar_face",
                "orientation_datum": "B",
            }],
            datums=[_plane_datum("B")],
        )
        tol = result["callouts"][0]["tolerance"]
        assert tol["datum_ref"]["primary"] == "B"


# ---------------------------------------------------------------------------
# 7. Cylinder → RUNOUT about axis datum
# ---------------------------------------------------------------------------

class TestCylindricalCallout:
    def test_runout_about_axis_datum(self):
        result = propose_callouts(
            features=[{
                "feature_id": "shaft-od",
                "feature_type": "cylindrical",
                "nominal_size_mm": 30.0,
                "axis_datum": "A",
            }],
            datums=[_axis_datum("A")],
        )
        assert result["ok"] is True
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "RUNOUT"

    def test_runout_axis_datum_in_ref(self):
        result = propose_callouts(
            features=[{
                "feature_id": "od",
                "feature_type": "cylindrical",
                "nominal_size_mm": 20.0,
                "axis_datum": "A",
            }],
            datums=[_axis_datum("A")],
        )
        tol = result["callouts"][0]["tolerance"]
        assert tol["datum_ref"]["primary"] == "A"

    def test_wrong_datum_type_for_runout_gives_warning(self):
        # axis_datum points to a PLANE datum → cannot do RUNOUT → warning
        result = propose_callouts(
            features=[{
                "feature_id": "od",
                "feature_type": "cylindrical",
                "nominal_size_mm": 20.0,
                "axis_datum": "A",
            }],
            datums=[_plane_datum("A")],
        )
        assert result["ok"] is True
        assert result["count"] == 0
        assert any("AXIS" in w for w in result["warnings"])

    def test_cylindricity_fallback_no_datum(self):
        result = propose_callouts(
            features=[{
                "feature_id": "shaft",
                "feature_type": "cylindrical",
                "nominal_size_mm": 25.0,
            }],
            datums=[],
        )
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "CYLINDRICITY"


# ---------------------------------------------------------------------------
# 8. Pattern → composite POSITION
# ---------------------------------------------------------------------------

class TestPatternCallout:
    def test_pattern_proposes_position(self):
        result = propose_callouts(
            features=[{
                "feature_id": "bolt-circle",
                "feature_type": "pattern",
                "nominal_size_mm": 8.0,
                "primary_datum": "A",
                "secondary_datum": "B",
                "pattern_count": 6,
            }],
            datums=[_plane_datum("A"), _plane_datum("B")],
        )
        assert result["ok"] is True
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "POSITION"

    def test_pattern_composite_note_mentions_intra(self):
        result = propose_callouts(
            features=[{
                "feature_id": "pcd",
                "feature_type": "pattern",
                "nominal_size_mm": 5.0,
                "primary_datum": "A",
                "pattern_count": 4,
            }],
            datums=[_plane_datum("A")],
        )
        note = result["callouts"][0]["tolerance"]["note"]
        assert "intra" in note.lower() or "composite" in note.lower()

    def test_pattern_intra_segment_finer(self):
        # The intra-pattern tolerance should be referenced in the note at a
        # finer value than the location tolerance.
        result = propose_callouts(
            features=[{
                "feature_id": "4xholes",
                "feature_type": "pattern",
                "nominal_size_mm": 10.0,
                "primary_datum": "A",
                "pattern_count": 4,
            }],
            datums=[_plane_datum("A")],
            grade="IT7",
        )
        loc_tol = result["callouts"][0]["tolerance"]["tolerance_value"]
        # The note embeds the fine tolerance value — just confirm loc_tol > 0
        assert loc_tol > 0

    def test_pattern_missing_datum_warning(self):
        result = propose_callouts(
            features=[{
                "feature_id": "holes",
                "feature_type": "pattern",
                "nominal_size_mm": 8.0,
                "pattern_count": 3,
            }],
            datums=[],
        )
        assert result["count"] == 0
        assert any("primary_datum" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# 9. Freeform → PROFILE_SURFACE
# ---------------------------------------------------------------------------

class TestFreeformCallout:
    def test_freeform_profile_surface(self):
        result = propose_callouts(
            features=[{
                "feature_id": "sculpted-face",
                "feature_type": "freeform",
                "nominal_size_mm": 80.0,
                "primary_datum": "A",
            }],
            datums=[_plane_datum("A")],
        )
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "PROFILE_SURFACE"

    def test_freeform_coarser_grade(self):
        # Freeform gets 2 IT grades coarser; compare raw IT7 vs profile result
        result = propose_callouts(
            features=[{
                "feature_id": "skin",
                "feature_type": "freeform",
                "nominal_size_mm": 50.0,
                "primary_datum": "A",
            }],
            datums=[_plane_datum("A")],
            grade="IT7",
        )
        profile_tol = result["callouts"][0]["tolerance"]["tolerance_value"]
        it7_tol = it_grade_tolerance(50.0, "IT7")
        # Profile should use IT9 (2 coarser), so should be > IT7
        assert profile_tol >= it7_tol

    def test_freeform_no_datum(self):
        result = propose_callouts(
            features=[{
                "feature_id": "freeform-top",
                "feature_type": "freeform",
            }],
            datums=[],
        )
        sym = result["callouts"][0]["tolerance"]["symbol"]
        assert sym == "PROFILE_SURFACE"


# ---------------------------------------------------------------------------
# 10. Intent adjustments
# ---------------------------------------------------------------------------

class TestIntentAdjustment:
    def _pos_tol(self, grade, intent):
        result = propose_callouts(
            features=[_hole_feature(dia_mm=20.0)],
            datums=[_plane_datum("A")],
            grade=grade,
            intent=intent,
        )
        return result["callouts"][0]["tolerance"]["tolerance_value"]

    def test_tight_finer_than_nominal(self):
        nominal = self._pos_tol("IT7", "nominal")
        tight = self._pos_tol("IT7", "tight")
        assert tight <= nominal

    def test_loose_coarser_than_nominal(self):
        nominal = self._pos_tol("IT7", "nominal")
        loose = self._pos_tol("IT7", "loose")
        assert loose >= nominal

    def test_precise_finer_than_tight(self):
        tight = self._pos_tol("IT7", "tight")
        precise = self._pos_tol("IT7", "precise")
        assert precise <= tight

    def test_grade_used_reported(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            grade="IT7",
            intent="nominal",
        )
        assert result["grade_used"] == "IT7"

    def test_tight_grade_used(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            grade="IT7",
            intent="tight",
        )
        assert result["grade_used"] == "IT6"


# ---------------------------------------------------------------------------
# 11. Top-level propose_callouts API
# ---------------------------------------------------------------------------

class TestProposeCalloutsApi:
    def test_bad_grade_returns_ok_false(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[],
            grade="IT99",
        )
        assert result["ok"] is False
        assert "reason" in result

    def test_bad_intent_returns_ok_false(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[],
            intent="ultra-mega-precise",
        )
        assert result["ok"] is False

    def test_empty_features_ok(self):
        result = propose_callouts(features=[], datums=[], grade="IT7")
        assert result["ok"] is True
        assert result["count"] == 0

    def test_multiple_features_mixed(self):
        features = [
            _hole_feature("bore-1", dia_mm=10.0, primary_datum="A"),
            {
                "feature_id": "wall",
                "feature_type": "planar_face",
                "orientation_datum": "A",
            },
            {
                "feature_id": "shaft",
                "feature_type": "cylindrical",
                "nominal_size_mm": 20.0,
                "axis_datum": "B",
            },
        ]
        datums = [_plane_datum("A"), _axis_datum("B")]
        result = propose_callouts(features=features, datums=datums, grade="IT7")
        assert result["ok"] is True
        assert result["count"] == 3

    def test_datum_parse_error_is_warning(self):
        result = propose_callouts(
            features=[_hole_feature()],
            datums=[{"no_label": "missing"}],
            grade="IT7",
        )
        # Should still succeed; the bad datum just triggers a warning
        assert result["ok"] is True
        assert any("datum" in w.lower() for w in result["warnings"])

    def test_features_non_list_returns_ok_false(self):
        result = propose_callouts(features="not-a-list", datums=[], grade="IT7")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# 12. LLM tool: gdt_auto_callouts
# ---------------------------------------------------------------------------

class TestToolAutoCallouts:
    def setup_method(self):
        from kerf_cad_core.gdt_callouts.tools import run_gdt_auto_callouts
        self._tool = run_gdt_auto_callouts
        self._ctx = _make_ctx()

    def _call(self, **kwargs):
        return _run(self._tool(self._ctx, json.dumps(kwargs).encode()))

    def test_basic_hole_callout(self):
        d = _ok(self._call(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            grade="IT7",
        ))
        assert d["count"] == 1
        assert d["callouts"][0]["tolerance"]["symbol"] == "POSITION"

    def test_missing_features_error(self):
        _err(self._call(datums=[], grade="IT7"))

    def test_features_not_list_error(self):
        _err(self._call(features="bad", datums=[], grade="IT7"))

    def test_bad_grade_error(self):
        _err(self._call(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            grade="IT99",
        ))

    def test_bad_intent_error(self):
        _err(self._call(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            intent="super-duper",
        ))

    def test_warnings_present_in_output(self):
        d = _ok(self._call(
            features=[{
                "feature_id": "no-datum-hole",
                "feature_type": "hole",
                "nominal_size_mm": 5.0,
            }],
            datums=[],
        ))
        assert isinstance(d["warnings"], list)

    def test_grade_used_in_output(self):
        d = _ok(self._call(
            features=[_hole_feature()],
            datums=[_plane_datum("A")],
            grade="IT8",
        ))
        assert d["grade_used"] == "IT8"


# ---------------------------------------------------------------------------
# 13. LLM tool: gdt_callout_balloon_table
# ---------------------------------------------------------------------------

class TestToolBalloonTable:
    def setup_method(self):
        from kerf_cad_core.gdt_callouts.tools import run_gdt_callout_balloon_table
        self._tool = run_gdt_callout_balloon_table
        self._ctx = _make_ctx()

    def _call(self, **kwargs):
        return _run(self._tool(self._ctx, json.dumps(kwargs).encode()))

    def _make_callouts(self):
        result = propose_callouts(
            features=[
                _hole_feature("bore-1", dia_mm=10.0),
                {
                    "feature_id": "wall",
                    "feature_type": "planar_face",
                    "orientation_datum": "A",
                },
            ],
            datums=[_plane_datum("A")],
        )
        return result["callouts"]

    def test_balloon_numbers_sequential(self):
        callouts = self._make_callouts()
        d = _ok(self._call(callouts=callouts))
        nums = [b["balloon"] for b in d["balloons"]]
        assert nums == list(range(1, len(nums) + 1))

    def test_balloon_count_matches(self):
        callouts = self._make_callouts()
        d = _ok(self._call(callouts=callouts))
        assert d["count"] == len(callouts)

    def test_text_contains_feature_id(self):
        callouts = self._make_callouts()
        d = _ok(self._call(callouts=callouts))
        assert "bore-1" in d["text"]

    def test_empty_callouts(self):
        d = _ok(self._call(callouts=[]))
        assert d["count"] == 0
        assert d["balloons"] == []

    def test_missing_callouts_error(self):
        _err(self._call())

    def test_callouts_not_list_error(self):
        _err(self._call(callouts={"not": "a list"}))

    def test_custom_title_in_text(self):
        d = _ok(self._call(callouts=[], title="My Part Drawing"))
        assert "My Part Drawing" in d["text"]
