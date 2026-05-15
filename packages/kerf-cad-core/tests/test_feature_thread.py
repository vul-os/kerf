"""
Tests for feature_thread (feature_tapped_hole, feature_thread_external,
thread_lookup) and thread_specs catalog.

Pure-Python: no database, no OCCT.
Tool-handler tests use a lightweight fake pool/ctx identical to the sibling
feature_hole_pattern test.

Author: imranparuk
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.feature_thread import (
    parse_designation,
    validate_tapped_hole_args,
    validate_external_thread_args,
    build_tapped_hole_node,
)
from kerf_cad_core.thread_specs import (
    METRIC_COARSE,
    METRIC_FINE,
    UTS_ALL,
    ALL_THREADS,
    metric_coarse_designations,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx(initial_content: str = ""):
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": "feature",
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            return (store["content"], store["kind"])

        def execute(self, query, *args):
            store["content"] = args[0]

    try:
        from kerf_core.utils.context import ProjectCtx
    except ImportError:
        pytest.skip("kerf_core not installed")

    ctx = ProjectCtx(
        pool=FakePool(),
        storage=None,
        project_id=project_id,
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return ctx, store, file_id


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def run_tapped_hole(ctx, file_id, **kwargs):
    from kerf_cad_core.feature_thread import run_feature_tapped_hole
    a = {"file_id": str(file_id), **kwargs}
    return json.loads(_run(run_feature_tapped_hole(ctx, json.dumps(a).encode())))


def run_external_thread(ctx, **kwargs):
    from kerf_cad_core.feature_thread import run_feature_thread_external
    return json.loads(_run(run_feature_thread_external(ctx, json.dumps(kwargs).encode())))


def run_lookup(ctx, designation):
    from kerf_cad_core.feature_thread import run_thread_lookup
    return json.loads(_run(run_thread_lookup(ctx, json.dumps({"designation": designation}).encode())))


# ---------------------------------------------------------------------------
# 1. parse_designation — metric coarse
# ---------------------------------------------------------------------------

class TestParseDesignationMetricCoarse:
    def test_m6_ok(self):
        r = parse_designation("M6")
        assert r["ok"] is True
        assert r["spec"]["major_dia_mm"] == 6.0
        assert r["spec"]["pitch_mm"] == 1.0

    def test_m3_ok(self):
        r = parse_designation("M3")
        assert r["ok"] is True
        assert r["spec"]["pitch_mm"] == 0.5

    def test_m10_ok(self):
        r = parse_designation("M10")
        assert r["ok"] is True
        assert r["spec"]["major_dia_mm"] == 10.0
        assert r["spec"]["pitch_mm"] == 1.5

    def test_m24_ok(self):
        r = parse_designation("M24")
        assert r["ok"] is True
        assert r["spec"]["pitch_mm"] == 3.0

    def test_m64_ok(self):
        r = parse_designation("M64")
        assert r["ok"] is True
        assert r["spec"]["major_dia_mm"] == 64.0

    def test_lowercase_m6_ok(self):
        r = parse_designation("m6")
        assert r["ok"] is True
        assert r["spec"]["major_dia_mm"] == 6.0

    def test_canonical_form_returned(self):
        r = parse_designation("m10")
        assert r["canonical"] == "M10"

    def test_tap_drill_m6(self):
        # M6 coarse: major=6, pitch=1; tap_drill = 6 - 1 = 5.0
        r = parse_designation("M6")
        assert r["spec"]["tap_drill_mm"] == pytest.approx(5.0, abs=0.01)

    def test_tap_drill_m10(self):
        # M10 coarse: pitch=1.5; tap_drill = 10 - 1.5 = 8.5
        r = parse_designation("M10")
        assert r["spec"]["tap_drill_mm"] == pytest.approx(8.5, abs=0.01)

    def test_tap_drill_m8(self):
        # M8 coarse: pitch=1.25; tap_drill = 8 - 1.25 = 6.75
        r = parse_designation("M8")
        assert r["spec"]["tap_drill_mm"] == pytest.approx(6.75, abs=0.01)

    def test_minor_dia_m6(self):
        # minor = 6 - 1.226869 * 1.0 = 4.7731...
        r = parse_designation("M6")
        assert r["spec"]["minor_dia_mm"] == pytest.approx(4.773, abs=0.002)

    def test_thread_class_metric(self):
        r = parse_designation("M6")
        assert r["spec"]["thread_class"] == "6H/6g"

    def test_system_metric(self):
        r = parse_designation("M6")
        assert r["spec"]["system"] == "metric"


# ---------------------------------------------------------------------------
# 2. parse_designation — metric fine
# ---------------------------------------------------------------------------

class TestParseDesignationMetricFine:
    def test_m6x075_ok(self):
        r = parse_designation("M6x0.75")
        assert r["ok"] is True
        assert r["spec"]["pitch_mm"] == 0.75

    def test_m10x1_ok(self):
        r = parse_designation("M10x1")
        assert r["ok"] is True
        assert r["spec"]["pitch_mm"] == 1.0

    def test_m12x125_ok(self):
        r = parse_designation("M12x1.25")
        assert r["ok"] is True
        assert r["spec"]["major_dia_mm"] == 12.0
        assert r["spec"]["pitch_mm"] == 1.25

    def test_m6x075_tap_drill(self):
        # tap_drill = 6 - 0.75 = 5.25
        r = parse_designation("M6x0.75")
        assert r["spec"]["tap_drill_mm"] == pytest.approx(5.25, abs=0.01)

    def test_series_fine(self):
        r = parse_designation("M6x0.75")
        assert r["spec"]["series"] == "fine"


# ---------------------------------------------------------------------------
# 3. parse_designation — UTS numbered sizes
# ---------------------------------------------------------------------------

class TestParseDesignationUTSNumbered:
    def test_10_24_unc_ok(self):
        r = parse_designation("#10-24 UNC")
        assert r["ok"] is True
        assert r["spec"]["system"] == "inch"
        assert r["spec"]["major_dia_in"] == pytest.approx(0.190, abs=0.001)

    def test_10_32_unf_ok(self):
        r = parse_designation("#10-32 UNF")
        assert r["ok"] is True
        assert r["spec"]["series"] == "fine"

    def test_6_32_unc_ok(self):
        r = parse_designation("#6-32 UNC")
        assert r["ok"] is True

    def test_4_40_unc_ok(self):
        r = parse_designation("#4-40 UNC")
        assert r["ok"] is True

    def test_unc_lowercase_suffix(self):
        r = parse_designation("#10-24 unc")
        assert r["ok"] is True

    def test_uts_thread_class(self):
        r = parse_designation("#10-24 UNC")
        assert r["spec"]["thread_class"] == "2B/2A"

    def test_uts_has_mm_fields(self):
        r = parse_designation("#10-24 UNC")
        assert "major_dia_mm" in r["spec"]
        assert r["spec"]["major_dia_mm"] == pytest.approx(0.190 * 25.4, abs=0.01)

    def test_tap_drill_10_24_unc(self):
        # P = 1/24 in; tap_drill_in = 0.190 - 1/24 = 0.1483...
        r = parse_designation("#10-24 UNC")
        expected = 0.190 - 1.0 / 24
        assert r["spec"]["tap_drill_in"] == pytest.approx(expected, abs=0.001)


# ---------------------------------------------------------------------------
# 4. parse_designation — UTS fractional sizes
# ---------------------------------------------------------------------------

class TestParseDesignationUTSFractional:
    def test_quarter_20_unc_ok(self):
        r = parse_designation("1/4-20 UNC")
        assert r["ok"] is True
        assert r["spec"]["major_dia_in"] == pytest.approx(0.250, abs=0.001)

    def test_quarter_28_unf_ok(self):
        r = parse_designation("1/4-28 UNF")
        assert r["ok"] is True

    def test_3_8_16_unc_ok(self):
        r = parse_designation("3/8-16 UNC")
        assert r["ok"] is True
        assert r["spec"]["major_dia_in"] == pytest.approx(0.375, abs=0.001)

    def test_half_13_unc_ok(self):
        r = parse_designation("1/2-13 UNC")
        assert r["ok"] is True

    def test_tap_drill_quarter_20_unc(self):
        # P = 1/20 = 0.05 in; tap_drill_in = 0.250 - 0.05 = 0.200
        r = parse_designation("1/4-20 UNC")
        assert r["spec"]["tap_drill_in"] == pytest.approx(0.200, abs=0.001)

    def test_uts_fractional_mm_fields(self):
        r = parse_designation("1/4-20 UNC")
        assert r["spec"]["major_dia_mm"] == pytest.approx(0.250 * 25.4, abs=0.01)


# ---------------------------------------------------------------------------
# 5. parse_designation — invalid/unknown designations
# ---------------------------------------------------------------------------

class TestParseDesignationInvalid:
    def test_empty_string(self):
        r = parse_designation("")
        assert r["ok"] is False
        assert len(r["errors"]) > 0

    def test_none(self):
        r = parse_designation(None)  # type: ignore[arg-type]
        assert r["ok"] is False

    def test_unknown_m_size(self):
        r = parse_designation("M99")
        assert r["ok"] is False

    def test_wrong_pitch_for_size(self):
        # M6x0.5 is not in catalog
        r = parse_designation("M6x0.5")
        assert r["ok"] is False

    def test_garbage_string(self):
        r = parse_designation("BSP 1/4")
        assert r["ok"] is False

    def test_errors_list_not_empty(self):
        r = parse_designation("M99")
        assert isinstance(r["errors"], list)
        assert len(r["errors"]) >= 1


# ---------------------------------------------------------------------------
# 6. thread_specs catalog completeness
# ---------------------------------------------------------------------------

class TestCatalogCompleteness:
    def test_all_m16_to_m64_coarse_present(self):
        """ISO 261 coarse series M1.6–M64 must all be in the catalog."""
        expected = [
            "M1.6", "M2", "M2.5", "M3", "M3.5", "M4", "M5", "M6",
            "M7", "M8", "M10", "M12", "M14", "M16", "M18", "M20",
            "M22", "M24", "M27", "M30", "M33", "M36", "M39", "M42",
            "M45", "M48", "M52", "M56", "M60", "M64",
        ]
        for d in expected:
            assert d in METRIC_COARSE, f"{d} missing from METRIC_COARSE"

    def test_metric_coarse_count(self):
        assert len(METRIC_COARSE) == 30

    def test_metric_fine_m6x075_present(self):
        assert "M6x0.75" in METRIC_FINE

    def test_uts_unc_1_4_20_present(self):
        assert "1/4-20 UNC" in UTS_ALL

    def test_uts_unf_1_4_28_present(self):
        assert "1/4-28 UNF" in UTS_ALL

    def test_all_threads_merged(self):
        # combined dict must be superset of both
        for k in METRIC_COARSE:
            assert k in ALL_THREADS
        for k in UTS_ALL:
            assert k in ALL_THREADS

    def test_coarse_designations_helper(self):
        desigs = metric_coarse_designations()
        assert "M6" in desigs
        assert "M64" in desigs
        assert len(desigs) == 30


# ---------------------------------------------------------------------------
# 7. validate_tapped_hole_args
# ---------------------------------------------------------------------------

class TestValidateTappedHoleArgs:
    def _call(self, designation="M6", depth=20.0, hole_type="blind",
              thread_depth=15.0, cb_dia=None, cb_dep=None,
              cs_dia=None, cs_ang=None):
        return validate_tapped_hole_args(
            designation, depth, hole_type, thread_depth,
            cb_dia, cb_dep, cs_dia, cs_ang,
        )

    def test_valid_blind(self):
        err, code, spec = self._call()
        assert err is None and code is None
        assert spec["major_dia_mm"] == 6.0

    def test_valid_through(self):
        err, code, spec = self._call(hole_type="through", thread_depth=None)
        assert err is None

    def test_invalid_designation(self):
        err, code, spec = self._call(designation="M99")
        assert code == "BAD_ARGS"
        assert spec is None

    def test_depth_zero_rejected(self):
        err, code, _ = self._call(depth=0)
        assert code == "BAD_ARGS"

    def test_thread_depth_exceeds_depth(self):
        err, code, _ = self._call(depth=10.0, thread_depth=15.0)
        assert code == "BAD_ARGS"

    def test_counterbore_too_small(self):
        # counterbore_dia must be > major_dia (6 mm)
        err, code, _ = self._call(cb_dia=5.0, cb_dep=3.0)
        assert code == "BAD_ARGS"

    def test_counterbore_missing_depth(self):
        err, code, _ = self._call(cb_dia=8.0, cb_dep=None)
        assert code == "BAD_ARGS"

    def test_countersink_angle_out_of_range(self):
        err, code, _ = self._call(cs_dia=10.0, cs_ang=20.0)
        assert code == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 8. validate_external_thread_args
# ---------------------------------------------------------------------------

class TestValidateExternalThreadArgs:
    def test_valid(self):
        err, code, spec = validate_external_thread_args(6.0, "M6", 20.0, None)
        assert err is None and code is None
        assert spec["major_dia_mm"] == 6.0

    def test_mismatch_rejected(self):
        err, code, _ = validate_external_thread_args(5.0, "M6", 20.0, None)
        assert code == "MISMATCH"
        assert "mismatch" in err.lower() or "match" in err.lower() or "does not match" in err.lower()

    def test_shaft_within_tolerance_ok(self):
        # 6.2 is within ±0.3 of M6 major_dia 6.0
        err, code, spec = validate_external_thread_args(6.2, "M6", 20.0, None)
        assert err is None

    def test_shaft_just_outside_tolerance(self):
        err, code, _ = validate_external_thread_args(6.4, "M6", 20.0, None)
        assert code == "MISMATCH"

    def test_length_zero_rejected(self):
        err, code, _ = validate_external_thread_args(6.0, "M6", 0.0, None)
        assert code == "BAD_ARGS"

    def test_invalid_designation(self):
        err, code, _ = validate_external_thread_args(6.0, "M99", 20.0, None)
        assert code == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 9. build_tapped_hole_node
# ---------------------------------------------------------------------------

class TestBuildTappedHoleNode:
    def _spec(self):
        return parse_designation("M6")["spec"]

    def test_required_fields(self):
        spec = self._spec()
        node = build_tapped_hole_node("tapped_hole-1", "M6", spec, 20.0, "blind", 15.0)
        assert node["id"] == "tapped_hole-1"
        assert node["op"] == "tapped_hole"
        assert node["designation"] == "M6"
        assert node["depth"] == 20.0
        assert node["hole_type"] == "blind"
        assert node["thread_depth"] == 15.0
        assert node["tap_drill_dia"] == pytest.approx(5.0, abs=0.01)
        assert node["cosmetic_thread"] is True

    def test_through_hole_thread_depth_equals_depth(self):
        spec = self._spec()
        node = build_tapped_hole_node("n", "M6", spec, 20.0, "through", None)
        assert node["thread_depth"] == 20.0

    def test_target_id_included(self):
        spec = self._spec()
        node = build_tapped_hole_node("n", "M6", spec, 20.0, "blind", 10.0, target_id="pad-1")
        assert node["target_id"] == "pad-1"

    def test_target_id_absent_when_empty(self):
        spec = self._spec()
        node = build_tapped_hole_node("n", "M6", spec, 20.0, "blind", 10.0)
        assert "target_id" not in node

    def test_counterbore_fields(self):
        spec = self._spec()
        node = build_tapped_hole_node(
            "n", "M6", spec, 20.0, "blind", 10.0,
            counterbore_dia=10.0, counterbore_depth=3.0,
        )
        assert node["counterbore_dia"] == 10.0
        assert node["counterbore_depth"] == 3.0

    def test_uts_node_has_inch_fields(self):
        spec = parse_designation("1/4-20 UNC")["spec"]
        node = build_tapped_hole_node("n", "1/4-20 UNC", spec, 15.0, "through", None)
        assert "major_dia_in" in node
        assert "pitch_in" in node

    def test_metric_node_no_inch_fields(self):
        spec = self._spec()
        node = build_tapped_hole_node("n", "M6", spec, 20.0, "through", None)
        assert "major_dia_in" not in node

    def test_json_round_trip(self):
        spec = self._spec()
        node = build_tapped_hole_node("tapped_hole-1", "M6", spec, 20.0, "blind", 15.0)
        assert json.loads(json.dumps(node)) == node


# ---------------------------------------------------------------------------
# 10. Tool handlers (fake DB) — requires kerf_core to be importable
# ---------------------------------------------------------------------------

@pytest.fixture
def _skip_no_kerf_core():
    try:
        from kerf_core.utils.context import ProjectCtx  # noqa: F401
    except ImportError:
        pytest.skip("kerf_core not installed")


class TestRunFeatureTappedHole:
    @pytest.fixture(autouse=True)
    def _skip(self, _skip_no_kerf_core):
        pass

    def test_missing_file_id(self):
        ctx, _, _ = make_ctx()
        from kerf_cad_core.feature_thread import run_feature_tapped_hole
        r = json.loads(_run(run_feature_tapped_hole(
            ctx, json.dumps({"designation": "M6", "depth": 20.0}).encode()
        )))
        assert "error" in r

    def test_missing_designation(self):
        ctx, _, fid = make_ctx()
        r = run_tapped_hole(ctx, fid, depth=20.0)
        assert "error" in r

    def test_invalid_designation(self):
        ctx, _, fid = make_ctx()
        r = run_tapped_hole(ctx, fid, designation="M99", depth=20.0)
        assert "error" in r
        assert r.get("code") == "BAD_ARGS"

    def test_through_hole_appends_node(self):
        ctx, store, fid = make_ctx()
        r = run_tapped_hole(ctx, fid, designation="M6", depth=20.0, hole_type="through")
        assert "error" not in r
        assert r["op"] == "tapped_hole"
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        node = doc["features"][0]
        assert node["op"] == "tapped_hole"
        assert node["designation"] == "M6"
        assert node["hole_type"] == "through"

    def test_blind_hole_appends_node(self):
        ctx, store, fid = make_ctx()
        r = run_tapped_hole(
            ctx, fid, designation="M6", depth=20.0,
            hole_type="blind", thread_depth=15.0,
        )
        assert "error" not in r
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["hole_type"] == "blind"
        assert node["thread_depth"] == 15.0

    def test_node_id_auto_increments(self):
        ctx, store, fid = make_ctx()
        run_tapped_hole(ctx, fid, designation="M6", depth=20.0)
        run_tapped_hole(ctx, fid, designation="M6", depth=20.0)
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"] == "tapped_hole-1"
        assert doc["features"][1]["id"] == "tapped_hole-2"

    def test_response_includes_tap_drill_dia(self):
        ctx, _, fid = make_ctx()
        r = run_tapped_hole(ctx, fid, designation="M6", depth=20.0)
        assert r.get("tap_drill_dia") == pytest.approx(5.0, abs=0.01)

    def test_uts_designation_accepted(self):
        ctx, store, fid = make_ctx()
        r = run_tapped_hole(ctx, fid, designation="1/4-20 UNC", depth=15.0)
        assert "error" not in r
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert "major_dia_in" in node


class TestRunFeatureThreadExternal:
    @pytest.fixture(autouse=True)
    def _skip(self, _skip_no_kerf_core):
        pass

    def test_valid_m6(self):
        ctx, _, _ = make_ctx()
        r = run_external_thread(ctx, shaft_dia=6.0, designation="M6", length=20.0)
        assert "error" not in r
        assert r["designation"] == "M6"
        assert r["cosmetic_thread"] is True

    def test_mismatch_error(self):
        ctx, _, _ = make_ctx()
        r = run_external_thread(ctx, shaft_dia=5.0, designation="M6", length=20.0)
        assert "error" in r
        assert r.get("code") == "MISMATCH"

    def test_missing_shaft_dia(self):
        ctx, _, _ = make_ctx()
        r = run_external_thread(ctx, designation="M6", length=20.0)
        assert "error" in r

    def test_uts_returns_inch_fields(self):
        ctx, _, _ = make_ctx()
        r = run_external_thread(ctx, shaft_dia=6.35, designation="1/4-20 UNC", length=15.0)
        assert "error" not in r
        assert "major_dia_in" in r
        assert "pitch_in" in r

    def test_thread_class_returned_in_result(self):
        ctx, _, _ = make_ctx()
        r = run_external_thread(ctx, shaft_dia=6.0, designation="M6", length=10.0)
        assert r.get("thread_class") == "6g"


class TestRunThreadLookup:
    @pytest.fixture(autouse=True)
    def _skip(self, _skip_no_kerf_core):
        pass

    def test_m6_lookup(self):
        ctx, _, _ = make_ctx()
        r = run_lookup(ctx, "M6")
        assert r.get("ok") is True
        assert r["spec"]["major_dia_mm"] == 6.0

    def test_uts_lookup(self):
        ctx, _, _ = make_ctx()
        r = run_lookup(ctx, "1/4-20 UNC")
        assert r.get("ok") is True
        assert "major_dia_in" in r["spec"]

    def test_unknown_designation(self):
        ctx, _, _ = make_ctx()
        r = run_lookup(ctx, "M99")
        assert r.get("ok") is False
        assert len(r["errors"]) > 0

    def test_missing_designation_param(self):
        from kerf_cad_core.feature_thread import run_thread_lookup
        ctx, _, _ = make_ctx()
        r = json.loads(_run(run_thread_lookup(ctx, json.dumps({}).encode())))
        assert "error" in r


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
