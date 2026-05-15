"""
Tests for kerf_cad_core.jewelry.findings

Pure-Python section (always runs):
  - compute_<family>_params: valid spec per kind, default dims, validation
  - compute_finding_params dispatcher: all families and kinds
  - _KIND_ALIASES: key aliases resolve correctly
  - LLM tool specs: names, required fields, enums
  - LLM tool runner jewelry_create_finding: success paths, node shape, errors
  - LLM tool runner jewelry_list_findings: all families, single family, error

OCC-gated section:
  - Skipped cleanly when pythonOCC absent.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.jewelry.findings import (
    _FAMILY_KINDS,
    _KIND_ALIASES,
    _VALID_BAIL_KINDS,
    _VALID_CLASP_KINDS,
    _VALID_EAR_FINDING_KINDS,
    _VALID_END_CAP_KINDS,
    _VALID_FAMILIES,
    _VALID_JUMP_RING_KINDS,
    _VALID_PIN_FINDING_KINDS,
    compute_bail_params,
    compute_clasp_params,
    compute_ear_finding_params,
    compute_end_cap_params,
    compute_finding_params,
    compute_jump_ring_params,
    compute_pin_finding_params,
    jewelry_create_finding_spec,
    jewelry_list_findings_spec,
    run_jewelry_create_finding,
    run_jewelry_list_findings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx(initial_content: str = "", kind: str = "feature"):
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": kind,
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class FakePool:
        def fetchone(self, query, *args):
            if store["kind"] == "NOT_FOUND":
                return None
            return (store["content"], store["kind"])

        def execute(self, query, *args):
            if args:
                store["content"] = args[0]

    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    except ImportError:
        class ProjectCtx:  # type: ignore[no-redef]
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

    ctx = ProjectCtx(
        pool=FakePool(),
        storage=None,
        project_id=project_id,
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return ctx, store, file_id


def run_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return json.loads(loop.run_until_complete(coro))
    finally:
        loop.close()


def run_create(ctx, file_id, **kwargs):
    args = {"file_id": str(file_id), **kwargs}
    return run_sync(run_jewelry_create_finding(ctx, json.dumps(args).encode()))


def run_list(**kwargs):
    ctx, _, _ = make_ctx()
    return run_sync(run_jewelry_list_findings(ctx, json.dumps(kwargs).encode()))


# ---------------------------------------------------------------------------
# compute_jump_ring_params
# ---------------------------------------------------------------------------

class TestJumpRingParams:
    @pytest.mark.parametrize("kind", sorted(_VALID_JUMP_RING_KINDS))
    def test_kind_produces_valid_spec(self, kind):
        p = compute_jump_ring_params(kind, wire_gauge_mm=1.0, inner_diameter_mm=5.0)
        assert p["family"] == "jump_ring"
        assert p["kind"] == kind
        assert p["wire_gauge_mm"] == pytest.approx(1.0)
        assert p["inner_diameter_mm"] == pytest.approx(5.0)
        assert "finding_hints" in p
        hints = p["finding_hints"]
        assert hints["inner_diameter_mm"] > 0
        assert hints["outer_diameter_mm"] > hints["inner_diameter_mm"]

    def test_round_hints_have_round_profile(self):
        p = compute_jump_ring_params("round_open", wire_gauge_mm=1.0, inner_diameter_mm=4.0)
        assert p["finding_hints"]["profile"] == "round"

    def test_oval_hints_have_oval_profile(self):
        p = compute_jump_ring_params("oval_open", wire_gauge_mm=1.0,
                                      inner_diameter_mm=4.0, aspect_ratio=1.5)
        h = p["finding_hints"]
        assert h["profile"] == "oval"
        assert h["aspect_ratio"] == pytest.approx(1.5)
        assert h["inner_length_mm"] == pytest.approx(4.0 * 1.5, rel=1e-3)

    def test_open_flag_on_open_kinds(self):
        p = compute_jump_ring_params("round_open", wire_gauge_mm=1.0, inner_diameter_mm=4.0)
        assert p["finding_hints"]["open"] is True

    def test_closed_flag_on_closed_kinds(self):
        p = compute_jump_ring_params("round_closed", wire_gauge_mm=1.0, inner_diameter_mm=4.0)
        assert p["finding_hints"]["open"] is False

    def test_quantity_default_is_one(self):
        p = compute_jump_ring_params("round_open", wire_gauge_mm=1.0, inner_diameter_mm=4.0)
        assert p["quantity"] == 1

    def test_quantity_batch(self):
        p = compute_jump_ring_params("round_open", wire_gauge_mm=1.0,
                                      inner_diameter_mm=4.0, quantity=50)
        assert p["quantity"] == 50

    def test_inner_diameter_must_exceed_gauge(self):
        with pytest.raises(ValueError, match="inner_diameter_mm"):
            compute_jump_ring_params("round_open", wire_gauge_mm=2.0, inner_diameter_mm=1.5)

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_jump_ring_params("round_open", wire_gauge_mm=0, inner_diameter_mm=4.0)

    def test_negative_inner_diameter_raises(self):
        with pytest.raises(ValueError, match="inner_diameter_mm must be > 0"):
            compute_jump_ring_params("round_open", wire_gauge_mm=1.0, inner_diameter_mm=-1.0)

    def test_oval_aspect_ratio_lt_one_raises(self):
        with pytest.raises(ValueError, match="aspect_ratio"):
            compute_jump_ring_params("oval_open", wire_gauge_mm=1.0,
                                      inner_diameter_mm=4.0, aspect_ratio=0.8)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown jump_ring kind"):
            compute_jump_ring_params("hexagonal", wire_gauge_mm=1.0, inner_diameter_mm=4.0)

    def test_unrealistic_gauge_raises(self):
        with pytest.raises(ValueError, match="unrealistically large"):
            compute_jump_ring_params("round_open", wire_gauge_mm=25.0, inner_diameter_mm=30.0)

    def test_quantity_zero_raises(self):
        with pytest.raises(ValueError, match="quantity must be a positive integer"):
            compute_jump_ring_params("round_open", wire_gauge_mm=1.0,
                                      inner_diameter_mm=4.0, quantity=0)

    def test_outer_diameter_equals_inner_plus_two_gauge(self):
        p = compute_jump_ring_params("round_closed", wire_gauge_mm=1.0, inner_diameter_mm=5.0)
        assert p["finding_hints"]["outer_diameter_mm"] == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# compute_bail_params
# ---------------------------------------------------------------------------

class TestBailParams:
    @pytest.mark.parametrize("kind", sorted(_VALID_BAIL_KINDS))
    def test_kind_produces_valid_spec(self, kind):
        p = compute_bail_params(kind, wire_gauge_mm=1.2)
        assert p["family"] == "bail"
        assert p["kind"] == kind
        assert p["wire_gauge_mm"] == pytest.approx(1.2)
        hints = p["finding_hints"]
        assert hints["body_length_mm"] > 0
        assert hints["body_width_mm"] > 0
        assert hints["loop_inner_diameter_mm"] > 0
        assert hints["loop_outer_diameter_mm"] > hints["loop_inner_diameter_mm"]

    def test_glue_on_has_pad(self):
        p = compute_bail_params("glue_on", wire_gauge_mm=1.0)
        hints = p["finding_hints"]
        assert "pad_width_mm" in hints
        assert hints["pad_width_mm"] > 0

    def test_pinch_has_spring_arms(self):
        p = compute_bail_params("pinch", wire_gauge_mm=1.0)
        assert p["finding_hints"]["spring_arm_count"] == 2

    def test_snap_has_clip_retention(self):
        p = compute_bail_params("snap", wire_gauge_mm=1.0)
        assert p["finding_hints"]["clip_retention"] == "spring_tab"

    def test_alias_clip_resolves_to_snap(self):
        p = compute_bail_params("clip", wire_gauge_mm=1.0)
        assert p["kind"] == "snap"

    def test_alias_loop_bail_resolves_to_loop(self):
        p = compute_bail_params("loop_bail", wire_gauge_mm=1.0)
        assert p["kind"] == "loop"

    def test_explicit_dims_used(self):
        p = compute_bail_params("loop", wire_gauge_mm=1.0,
                                 body_length_mm=10.0, body_width_mm=4.0)
        assert p["finding_hints"]["body_length_mm"] == pytest.approx(10.0)
        assert p["finding_hints"]["body_width_mm"] == pytest.approx(4.0)

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_bail_params("pinch", wire_gauge_mm=0)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown bail kind"):
            compute_bail_params("tube", wire_gauge_mm=1.0)


# ---------------------------------------------------------------------------
# compute_ear_finding_params
# ---------------------------------------------------------------------------

class TestEarFindingParams:
    @pytest.mark.parametrize("kind", sorted(_VALID_EAR_FINDING_KINDS))
    def test_kind_produces_valid_spec(self, kind):
        p = compute_ear_finding_params(kind, wire_gauge_mm=0.8)
        assert p["family"] == "ear_finding"
        assert p["kind"] == kind
        assert p["wire_gauge_mm"] == pytest.approx(0.8)
        assert "finding_hints" in p

    def test_fish_hook_has_curl_radius(self):
        p = compute_ear_finding_params("fish_hook", wire_gauge_mm=0.8)
        hints = p["finding_hints"]
        assert hints["curl_radius_mm"] == pytest.approx(hints["hook_width_mm"] / 2.0, rel=1e-3)

    def test_lever_back_has_mechanism(self):
        p = compute_ear_finding_params("lever_back", wire_gauge_mm=0.8)
        assert p["finding_hints"]["lever_mechanism"] == "hinged"

    def test_post_butterfly_has_butterfly_span(self):
        p = compute_ear_finding_params("post_butterfly", wire_gauge_mm=0.8)
        hints = p["finding_hints"]
        assert "butterfly_span_mm" in hints
        assert hints["butterfly_span_mm"] > 0

    def test_screw_back_has_thread_pitch(self):
        p = compute_ear_finding_params("screw_back", wire_gauge_mm=0.8)
        hints = p["finding_hints"]
        assert "thread_pitch_mm" in hints
        assert hints["thread_pitch_mm"] > 0

    def test_huggie_outer_greater_than_inner(self):
        p = compute_ear_finding_params("huggie", wire_gauge_mm=1.0)
        hints = p["finding_hints"]
        assert hints["outer_diameter_mm"] > hints["inner_diameter_mm"]

    def test_kidney_has_closure_type(self):
        p = compute_ear_finding_params("kidney", wire_gauge_mm=0.8)
        assert p["finding_hints"]["kidney_closure"] == "wire_through_loop"

    def test_ear_nut_has_post_hole(self):
        p = compute_ear_finding_params("ear_nut", wire_gauge_mm=0.8)
        hints = p["finding_hints"]
        assert hints["post_hole_diameter_mm"] > 0
        # Post hole should be slightly larger than wire gauge (clearance)
        assert hints["post_hole_diameter_mm"] > 0.8

    def test_alias_shepherd_resolves_to_fish_hook(self):
        p = compute_ear_finding_params("shepherd", wire_gauge_mm=0.8)
        assert p["kind"] == "fish_hook"

    def test_alias_butterfly_resolves_to_post_butterfly(self):
        p = compute_ear_finding_params("butterfly", wire_gauge_mm=0.8)
        assert p["kind"] == "post_butterfly"

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_ear_finding_params("fish_hook", wire_gauge_mm=0)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown ear_finding kind"):
            compute_ear_finding_params("clip_on", wire_gauge_mm=0.8)


# ---------------------------------------------------------------------------
# compute_pin_finding_params
# ---------------------------------------------------------------------------

class TestPinFindingParams:
    @pytest.mark.parametrize("kind", sorted(_VALID_PIN_FINDING_KINDS))
    def test_kind_produces_valid_spec(self, kind):
        p = compute_pin_finding_params(kind, wire_gauge_mm=0.9)
        assert p["family"] == "pin_finding"
        assert p["kind"] == kind
        assert "finding_hints" in p

    def test_pin_stem_has_tip_type(self):
        p = compute_pin_finding_params("pin_stem", wire_gauge_mm=0.9)
        assert p["finding_hints"]["tip_type"] == "tapered_point"

    def test_pin_stem_default_length(self):
        p = compute_pin_finding_params("pin_stem", wire_gauge_mm=1.0)
        # Default: gauge × 20 = 20.0
        assert p["finding_hints"]["stem_length_mm"] == pytest.approx(20.0)

    def test_pin_stem_explicit_length(self):
        p = compute_pin_finding_params("pin_stem", wire_gauge_mm=1.0, stem_length_mm=35.0)
        assert p["finding_hints"]["stem_length_mm"] == pytest.approx(35.0)

    def test_joint_barrel_dims_positive(self):
        p = compute_pin_finding_params("joint", wire_gauge_mm=1.0)
        hints = p["finding_hints"]
        assert hints["barrel_outer_diameter_mm"] > 0
        assert hints["barrel_inner_diameter_mm"] > 0
        assert hints["barrel_length_mm"] > 0

    def test_catch_rotating_mechanism(self):
        p = compute_pin_finding_params("catch_rotating", wire_gauge_mm=1.0)
        assert p["finding_hints"]["mechanism"] == "rotating_frame"

    def test_catch_roller_mechanism(self):
        p = compute_pin_finding_params("catch_roller", wire_gauge_mm=1.0)
        assert p["finding_hints"]["mechanism"] == "roller"

    def test_safety_catch_flag(self):
        p = compute_pin_finding_params("catch_rotating", wire_gauge_mm=1.0, safety_catch=True)
        assert p["finding_hints"]["safety_catch"] is True

    def test_stick_pin_has_guard_cap(self):
        p = compute_pin_finding_params("stick_pin", wire_gauge_mm=0.8)
        assert p["finding_hints"]["guard_cap"] is True

    def test_alias_rotating_catch_resolves(self):
        p = compute_pin_finding_params("rotating_catch", wire_gauge_mm=1.0)
        assert p["kind"] == "catch_rotating"

    def test_alias_roller_catch_resolves(self):
        p = compute_pin_finding_params("roller_catch", wire_gauge_mm=1.0)
        assert p["kind"] == "catch_roller"

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_pin_finding_params("pin_stem", wire_gauge_mm=0)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown pin_finding kind"):
            compute_pin_finding_params("cotter_pin", wire_gauge_mm=1.0)


# ---------------------------------------------------------------------------
# compute_end_cap_params
# ---------------------------------------------------------------------------

class TestEndCapParams:
    @pytest.mark.parametrize("kind", sorted(_VALID_END_CAP_KINDS))
    def test_kind_produces_valid_spec(self, kind):
        p = compute_end_cap_params(kind, wire_gauge_mm=0.7)
        assert p["family"] == "end_cap"
        assert p["kind"] == kind
        assert "finding_hints" in p

    def test_glue_in_has_loop(self):
        p = compute_end_cap_params("glue_in", wire_gauge_mm=1.0)
        hints = p["finding_hints"]
        assert hints["attachment"] == "glue"
        assert hints["loop_outer_diameter_mm"] > 0

    def test_crimp_wall_equals_gauge(self):
        p = compute_end_cap_params("crimp", wire_gauge_mm=0.5)
        assert p["finding_hints"]["wall_thickness_mm"] == pytest.approx(0.5)

    def test_cord_end_has_clearance(self):
        p = compute_end_cap_params("cord_end", wire_gauge_mm=0.5, cord_diameter_mm=3.0)
        hints = p["finding_hints"]
        assert hints["cap_inner_diameter_mm"] > hints["cord_diameter_mm"]

    def test_ribbon_clamp_tooth_count_positive(self):
        p = compute_end_cap_params("ribbon_clamp", wire_gauge_mm=0.5, ribbon_width_mm=10.0)
        assert p["finding_hints"]["tooth_count"] >= 2

    def test_connector_link_outer_gt_inner(self):
        p = compute_end_cap_params("connector_link", wire_gauge_mm=1.0)
        hints = p["finding_hints"]
        assert hints["link_outer_diameter_mm"] > hints["link_inner_diameter_mm"]

    def test_figure_8_has_two_rings(self):
        p = compute_end_cap_params("figure_8", wire_gauge_mm=1.0,
                                    ring_inner_diameter_mm=4.0)
        assert p["finding_hints"]["ring_count"] == 2

    def test_split_ring_helix_coil(self):
        p = compute_end_cap_params("split_ring", wire_gauge_mm=0.8)
        hints = p["finding_hints"]
        assert hints["form"] == "helical_coil"
        assert hints["coil_turns"] > 2.0

    def test_alias_cord_end_cap_resolves(self):
        p = compute_end_cap_params("cord_end_cap", wire_gauge_mm=0.5,
                                    cord_diameter_mm=3.0)
        assert p["kind"] == "cord_end"

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_end_cap_params("crimp", wire_gauge_mm=0)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown end_cap kind"):
            compute_end_cap_params("tube_end", wire_gauge_mm=1.0)


# ---------------------------------------------------------------------------
# compute_clasp_params
# ---------------------------------------------------------------------------

class TestClaspParams:
    @pytest.mark.parametrize("kind", sorted(_VALID_CLASP_KINDS))
    def test_kind_produces_valid_spec(self, kind):
        p = compute_clasp_params(kind, wire_gauge_mm=1.0)
        assert p["family"] == "clasp"
        assert p["kind"] == kind
        assert "finding_hints" in p

    def test_hook_and_eye_has_eye_dims(self):
        p = compute_clasp_params("hook_and_eye", wire_gauge_mm=1.0)
        hints = p["finding_hints"]
        assert hints["eye_outer_diameter_mm"] > hints["eye_inner_diameter_mm"]

    def test_magnetic_cap_smaller_than_magnet(self):
        p = compute_clasp_params("magnetic", wire_gauge_mm=1.0,
                                  magnet_diameter_mm=8.0)
        hints = p["finding_hints"]
        assert hints["cap_outer_diameter_mm"] > hints["magnet_diameter_mm"]

    def test_s_clasp_has_total_length(self):
        p = compute_clasp_params("s_clasp", wire_gauge_mm=1.0)
        assert p["finding_hints"]["total_length_mm"] > 0

    def test_barrel_has_thread_pitch(self):
        p = compute_clasp_params("barrel", wire_gauge_mm=1.0)
        assert p["finding_hints"]["thread_pitch_mm"] > 0

    def test_barrel_inner_lt_outer(self):
        p = compute_clasp_params("barrel", wire_gauge_mm=0.8,
                                  barrel_diameter_mm=6.0)
        hints = p["finding_hints"]
        assert hints["barrel_outer_diameter_mm"] > hints["barrel_inner_diameter_mm"]

    def test_slide_lock_has_travel(self):
        p = compute_clasp_params("slide_lock", wire_gauge_mm=1.0)
        assert p["finding_hints"]["slide_travel_mm"] > 0

    def test_alias_torpedo_resolves_to_barrel(self):
        p = compute_clasp_params("torpedo", wire_gauge_mm=1.0)
        assert p["kind"] == "barrel"

    def test_alias_hook_eye_resolves(self):
        p = compute_clasp_params("hook_eye", wire_gauge_mm=1.0)
        assert p["kind"] == "hook_and_eye"

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_clasp_params("barrel", wire_gauge_mm=0)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown clasp kind"):
            compute_clasp_params("lobster", wire_gauge_mm=1.0)


# ---------------------------------------------------------------------------
# compute_finding_params dispatcher
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_all_families_all_kinds_smoke(self):
        """Every family × kind combination must produce a spec without raising."""
        gauge = 1.0
        extra: dict[str, dict] = {
            "jump_ring": {"inner_diameter_mm": 5.0},
            "bail": {},
            "ear_finding": {},
            "pin_finding": {},
            "end_cap": {},
            "clasp": {},
        }
        for family, kinds in _FAMILY_KINDS.items():
            for kind in kinds:
                p = compute_finding_params(family, kind, gauge, **extra[family])
                assert p["family"] == family, f"{family}/{kind}: wrong family"
                assert p["kind"] == kind, f"{family}/{kind}: wrong kind"

    def test_unknown_family_raises(self):
        with pytest.raises(ValueError, match="Unknown finding family"):
            compute_finding_params("pendant", "round", 1.0)

    def test_alias_in_dispatcher(self):
        p = compute_finding_params("jump_ring", "round_open", 1.0, inner_diameter_mm=5.0)
        assert p["family"] == "jump_ring"
        assert p["kind"] == "round_open"


# ---------------------------------------------------------------------------
# KIND_ALIASES sanity
# ---------------------------------------------------------------------------

class TestKindAliases:
    def test_all_alias_targets_are_valid_kinds(self):
        """Every alias target must exist in some family's kind set."""
        all_kinds = set()
        for kinds in _FAMILY_KINDS.values():
            all_kinds |= kinds
        for alias, target in _KIND_ALIASES.items():
            assert target in all_kinds, (
                f"Alias {alias!r} → {target!r} is not a valid kind in any family"
            )


# ---------------------------------------------------------------------------
# ToolSpec declarations
# ---------------------------------------------------------------------------

class TestToolSpecs:
    def test_create_finding_spec_name(self):
        assert jewelry_create_finding_spec.name == "jewelry_create_finding"

    def test_create_finding_required_fields(self):
        req = set(jewelry_create_finding_spec.input_schema["required"])
        assert "file_id" in req
        assert "family" in req
        assert "kind" in req
        assert "wire_gauge_mm" in req

    def test_create_finding_family_enum_complete(self):
        props = jewelry_create_finding_spec.input_schema["properties"]
        assert set(props["family"]["enum"]) == _VALID_FAMILIES

    def test_list_findings_spec_name(self):
        assert jewelry_list_findings_spec.name == "jewelry_list_findings"

    def test_list_findings_family_enum_complete(self):
        props = jewelry_list_findings_spec.input_schema["properties"]
        assert set(props["family"]["enum"]) == _VALID_FAMILIES


# ---------------------------------------------------------------------------
# LLM tool: jewelry_list_findings
# ---------------------------------------------------------------------------

class TestListFindingsTool:
    def test_no_family_returns_all(self):
        r = run_list()
        assert "error" not in r, r
        assert set(r.keys()) == _VALID_FAMILIES

    def test_family_filter_returns_kinds(self):
        r = run_list(family="bail")
        assert "error" not in r, r
        assert r["family"] == "bail"
        assert set(r["kinds"]) == _VALID_BAIL_KINDS

    def test_all_families_filterable(self):
        for fam in _VALID_FAMILIES:
            r = run_list(family=fam)
            assert "error" not in r, f"family={fam}: {r}"
            assert set(r["kinds"]) == _FAMILY_KINDS[fam]

    def test_unknown_family_returns_error(self):
        r = run_list(family="widget")
        assert "error" in r

    def test_empty_args(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_list_findings(ctx, b"{}"))
        assert "error" not in r


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_finding — success paths
# ---------------------------------------------------------------------------

class TestCreateFindingTool:
    def test_jump_ring_round_open(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, family="jump_ring", kind="round_open",
                       wire_gauge_mm=1.0, inner_diameter_mm=5.0)
        assert "error" not in r, r
        assert r["op"] == "finding"
        assert r["family"] == "jump_ring"
        assert r["kind"] == "round_open"

    def test_node_appended_to_feature_doc(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="bail", kind="pinch", wire_gauge_mm=1.2)
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        node = doc["features"][0]
        assert node["op"] == "finding"
        assert node["family"] == "bail"

    def test_node_id_starts_with_finding(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="ear_finding", kind="fish_hook", wire_gauge_mm=0.8)
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"].startswith("finding-")

    def test_explicit_node_id_used(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, family="bail", kind="loop",
                       wire_gauge_mm=1.0, id="my-bail-1")
        assert "error" not in r
        assert r["id"] == "my-bail-1"

    def test_second_node_increments_id(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="bail", kind="loop", wire_gauge_mm=1.0)
        r2 = run_create(ctx, fid, family="ear_finding", kind="kidney", wire_gauge_mm=0.8)
        assert "error" not in r2
        assert r2["id"] == "finding-2"

    @pytest.mark.parametrize("family,kind,extra", [
        ("jump_ring",   "round_open",     {"inner_diameter_mm": 5.0}),
        ("jump_ring",   "oval_closed",    {"inner_diameter_mm": 4.0, "aspect_ratio": 1.4}),
        ("bail",        "pinch",          {}),
        ("bail",        "snap",           {}),
        ("bail",        "glue_on",        {}),
        ("bail",        "loop",           {}),
        ("ear_finding", "fish_hook",      {}),
        ("ear_finding", "lever_back",     {}),
        ("ear_finding", "post_butterfly", {}),
        ("ear_finding", "screw_back",     {}),
        ("ear_finding", "huggie",         {}),
        ("ear_finding", "kidney",         {}),
        ("ear_finding", "ear_nut",        {}),
        ("pin_finding", "pin_stem",       {}),
        ("pin_finding", "joint",          {}),
        ("pin_finding", "catch_rotating", {}),
        ("pin_finding", "catch_roller",   {}),
        ("pin_finding", "stick_pin",      {}),
        ("end_cap",     "glue_in",        {}),
        ("end_cap",     "crimp",          {}),
        ("end_cap",     "cord_end",       {}),
        ("end_cap",     "ribbon_clamp",   {}),
        ("end_cap",     "connector_link", {}),
        ("end_cap",     "figure_8",       {}),
        ("end_cap",     "split_ring",     {}),
        ("clasp",       "hook_and_eye",   {}),
        ("clasp",       "magnetic",       {}),
        ("clasp",       "s_clasp",        {}),
        ("clasp",       "barrel",         {}),
        ("clasp",       "slide_lock",     {}),
    ])
    def test_all_kinds_succeed(self, family, kind, extra):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, family=family, kind=kind,
                       wire_gauge_mm=1.0, **extra)
        assert "error" not in r, f"{family}/{kind}: {r}"

    def test_node_contains_all_required_keys(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="bail", kind="pinch", wire_gauge_mm=1.0)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        for key in ("op", "family", "kind", "wire_gauge_mm", "finding_hints"):
            assert key in node, f"Missing key {key!r} in finding node"

    def test_finding_hints_embedded_in_feature_doc(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="jump_ring", kind="round_open",
                   wire_gauge_mm=1.0, inner_diameter_mm=5.0)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert isinstance(node["finding_hints"], dict)
        assert node["finding_hints"]["inner_diameter_mm"] > 0

    def test_alias_accepted_in_tool(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, family="ear_finding", kind="shepherd",
                       wire_gauge_mm=0.8)
        assert "error" not in r
        doc = json.loads(store["content"])
        assert doc["features"][0]["kind"] == "fish_hook"

    def test_quantity_passed_through(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="jump_ring", kind="round_open",
                   wire_gauge_mm=1.0, inner_diameter_mm=5.0, quantity=20)
        doc = json.loads(store["content"])
        assert doc["features"][0]["quantity"] == 20

    def test_safety_catch_passed_through(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, family="pin_finding", kind="catch_rotating",
                   wire_gauge_mm=1.0, safety_catch=True)
        doc = json.loads(store["content"])
        assert doc["features"][0]["finding_hints"]["safety_catch"] is True


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_finding — error paths
# ---------------------------------------------------------------------------

class TestCreateFindingToolErrors:
    def test_missing_file_id(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_create_finding(
            ctx, json.dumps({
                "family": "bail", "kind": "pinch", "wire_gauge_mm": 1.0
            }).encode()
        ))
        assert "error" in r

    def test_missing_family(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, kind="pinch", wire_gauge_mm=1.0)
        assert "error" in r

    def test_missing_kind(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="bail", wire_gauge_mm=1.0)
        assert "error" in r

    def test_missing_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_sync(run_jewelry_create_finding(
            ctx, json.dumps({
                "file_id": str(fid), "family": "bail", "kind": "pinch"
            }).encode()
        ))
        assert "error" in r

    def test_unknown_family(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="widget", kind="round", wire_gauge_mm=1.0)
        assert "error" in r

    def test_unknown_kind(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="bail", kind="tube_bail", wire_gauge_mm=1.0)
        assert "error" in r

    def test_invalid_file_id_uuid(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_create_finding(
            ctx, json.dumps({
                "file_id": "not-a-uuid", "family": "bail",
                "kind": "pinch", "wire_gauge_mm": 1.0
            }).encode()
        ))
        assert "error" in r

    def test_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        r = run_create(ctx, fid, family="bail", kind="pinch", wire_gauge_mm=1.0)
        assert "error" in r

    def test_zero_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="bail", kind="pinch", wire_gauge_mm=0)
        assert "error" in r

    def test_negative_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="bail", kind="pinch", wire_gauge_mm=-0.5)
        assert "error" in r

    def test_invalid_json(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_create_finding(ctx, b"not json!"))
        assert "error" in r

    def test_jump_ring_inner_diameter_too_small(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="jump_ring", kind="round_open",
                       wire_gauge_mm=2.0, inner_diameter_mm=1.0)
        assert "error" in r

    def test_non_numeric_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_sync(run_jewelry_create_finding(
            ctx, json.dumps({
                "file_id": str(fid), "family": "bail", "kind": "pinch",
                "wire_gauge_mm": "thick"
            }).encode()
        ))
        assert "error" in r

    def test_quantity_zero_raises(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, family="jump_ring", kind="round_open",
                       wire_gauge_mm=1.0, inner_diameter_mm=5.0, quantity=0)
        assert "error" in r


# ---------------------------------------------------------------------------
# OCC-gated tests
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.occ_helpers import _OCC_AVAILABLE as _OCC
except ImportError:
    _OCC = False

pytestmark_occ = pytest.mark.skipif(
    not _OCC,
    reason="pythonOCC not installed; skip findings OCC smoke tests"
)


@pytestmark_occ
class TestFindingsOCC:
    """Structural checks confirming node-spec keys are complete for the worker."""

    def test_finding_node_has_required_worker_keys(self):
        p = compute_jump_ring_params("round_open", wire_gauge_mm=1.0, inner_diameter_mm=5.0)
        required = {"family", "kind", "wire_gauge_mm", "finding_hints"}
        missing = required - set(p.keys())
        assert not missing, f"Missing keys for worker: {missing}"

    def test_all_families_have_finding_hints_dict(self):
        gauge = 1.0
        combos = [
            ("jump_ring",   "round_open",     {"inner_diameter_mm": 5.0}),
            ("bail",        "pinch",          {}),
            ("ear_finding", "fish_hook",      {}),
            ("pin_finding", "pin_stem",       {}),
            ("end_cap",     "crimp",          {}),
            ("clasp",       "hook_and_eye",   {}),
        ]
        for family, kind, kw in combos:
            p = compute_finding_params(family, kind, gauge, **kw)
            assert isinstance(p["finding_hints"], dict), (
                f"{family}/{kind}: finding_hints must be a dict"
            )
