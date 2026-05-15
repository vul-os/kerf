"""
Tests for kerf_cad_core.jewelry.chain

Pure-Python section (always runs):
  - compute_chain_params: all link styles, length sources, validation
  - compute_clasp_params: all clasp styles, validation
  - chain_length_to_link_count / link_count_to_chain_length round-trips
  - standard_length_names: sanity
  - LLM tool specs: names, required fields, enums
  - LLM tool runner jewelry_create_chain: success paths, node shape, error paths
  - LLM tool runner jewelry_chain_length: success paths, error paths

OCC-gated section:
  - Skipped cleanly when pythonOCC absent.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.jewelry.chain import (
    _VALID_LINK_STYLES,
    _VALID_CLASP_STYLES,
    _STANDARD_LENGTHS_MM,
    _STYLE_ALIASES,
    compute_chain_params,
    compute_clasp_params,
    chain_length_to_link_count,
    link_count_to_chain_length,
    link_pitch,
    standard_length_names,
    jewelry_create_chain_spec,
    jewelry_chain_length_spec,
    run_jewelry_create_chain,
    run_jewelry_chain_length,
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
    return run_sync(run_jewelry_create_chain(ctx, json.dumps(args).encode()))


def run_length(**kwargs):
    ctx, _, _ = make_ctx()
    return run_sync(run_jewelry_chain_length(ctx, json.dumps(kwargs).encode()))


# ---------------------------------------------------------------------------
# compute_chain_params — basic per-style smoke tests
# ---------------------------------------------------------------------------

class TestComputeChainParamsStyles:
    """Every link style should produce a valid spec from minimal inputs."""

    @pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
    def test_style_link_count(self, style):
        p = compute_chain_params(style, wire_gauge_mm=1.0, link_count=100)
        assert p["style"] == style
        assert p["link_count"] == 100
        assert p["link_length_mm"] > 0
        assert p["link_width_mm"] > 0
        assert p["link_pitch_mm"] > 0
        assert p["total_length_mm"] > 0
        assert p["wire_gauge_mm"] == pytest.approx(1.0)
        assert "link_hints" in p
        assert p["open_ends"] is True

    @pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
    def test_style_total_length(self, style):
        p = compute_chain_params(style, wire_gauge_mm=1.2, total_length_mm=450.0)
        assert p["link_count"] >= 1
        # Actual length should be within one pitch of the target
        assert abs(p["total_length_mm"] - p["link_count"] * p["link_pitch_mm"]) < 1e-3

    @pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
    def test_style_standard_length(self, style):
        p = compute_chain_params(
            style, wire_gauge_mm=1.0, standard_length="bracelet_7in"
        )
        assert p["link_count"] >= 1
        assert p["total_length_mm"] > 0

    def test_link_hints_type_key(self):
        """Each style's link_hints dict should have a 'type' key."""
        for style in _VALID_LINK_STYLES:
            p = compute_chain_params(style, wire_gauge_mm=1.0, link_count=10)
            hints = p["link_hints"]
            assert "type" in hints, f"Style {style!r}: missing 'type' in link_hints"


class TestComputeChainParamsLinkDimDefaults:
    def test_cable_defaults_reasonable(self):
        p = compute_chain_params("cable", wire_gauge_mm=1.0, link_count=50)
        # Default multiplier: length 3.5×, width 2.5×
        assert abs(p["link_length_mm"] - 3.5) < 0.01
        assert abs(p["link_width_mm"] - 2.5) < 0.01

    def test_explicit_link_dims_used(self):
        p = compute_chain_params(
            "cable", wire_gauge_mm=1.0,
            link_length_mm=5.0, link_width_mm=3.0,
            link_count=50
        )
        assert p["link_length_mm"] == pytest.approx(5.0)
        assert p["link_width_mm"] == pytest.approx(3.0)


class TestComputeChainParamsCurbVariants:
    def test_curb_diamond_cut_hint(self):
        p = compute_chain_params(
            "curb", wire_gauge_mm=1.2, link_count=60, diamond_cut=True
        )
        assert p["link_hints"]["diamond_cut"] is True
        assert p["link_hints"]["diamond_facets"] == 4

    def test_curb_flat_hint(self):
        p = compute_chain_params(
            "curb", wire_gauge_mm=1.2, link_count=60, flat=True
        )
        assert p["link_hints"]["flat_face"] is True
        assert p["link_hints"]["flat_ratio"] == pytest.approx(0.6)

    def test_alias_anchor_normalises_to_mariner(self):
        p = compute_chain_params("anchor", wire_gauge_mm=1.5, link_count=30)
        assert p["style"] == "mariner"


class TestComputeChainParamsFigaro:
    def test_figaro_long_link_ratio_stored(self):
        p = compute_chain_params(
            "figaro", wire_gauge_mm=1.0, link_count=40, long_link_ratio=3.0
        )
        hints = p["link_hints"]
        assert hints["type"] == "figaro"
        assert hints["long_link_length_mm"] == pytest.approx(
            p["link_length_mm"] * 3.0, rel=1e-3
        )


class TestComputeChainParamsRope:
    def test_rope_twist_angle_stored(self):
        p = compute_chain_params(
            "rope", wire_gauge_mm=0.8, link_count=200, twist_angle_deg=60.0
        )
        assert p["link_hints"]["twist_angle_deg"] == pytest.approx(60.0)


class TestComputeChainParamsValidation:
    def test_unknown_style_raises(self):
        with pytest.raises(ValueError, match="Unknown chain style"):
            compute_chain_params("curly", wire_gauge_mm=1.0, link_count=10)

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_chain_params("cable", wire_gauge_mm=0, link_count=10)

    def test_negative_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_chain_params("cable", wire_gauge_mm=-1.0, link_count=10)

    def test_unrealistic_gauge_raises(self):
        with pytest.raises(ValueError, match="unrealistically large"):
            compute_chain_params("cable", wire_gauge_mm=25.0, link_count=10)

    def test_zero_link_length_raises(self):
        with pytest.raises(ValueError, match="link_length_mm must be > 0"):
            compute_chain_params(
                "cable", wire_gauge_mm=1.0, link_length_mm=0, link_count=10
            )

    def test_link_length_less_than_gauge_raises(self):
        with pytest.raises(ValueError, match="link_length_mm"):
            compute_chain_params(
                "cable", wire_gauge_mm=2.0, link_length_mm=1.0, link_count=10
            )

    def test_no_length_source_raises(self):
        with pytest.raises(ValueError, match="One of link_count"):
            compute_chain_params("cable", wire_gauge_mm=1.0)

    def test_two_length_sources_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            compute_chain_params(
                "cable", wire_gauge_mm=1.0,
                link_count=10, total_length_mm=200.0
            )

    def test_all_three_length_sources_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            compute_chain_params(
                "cable", wire_gauge_mm=1.0,
                link_count=10, total_length_mm=200.0, standard_length="bracelet_7in"
            )

    def test_zero_total_length_raises(self):
        with pytest.raises(ValueError, match="total_length_mm must be > 0"):
            compute_chain_params("cable", wire_gauge_mm=1.0, total_length_mm=0)

    def test_zero_link_count_raises(self):
        with pytest.raises(ValueError, match="positive integer"):
            compute_chain_params("cable", wire_gauge_mm=1.0, link_count=0)

    def test_unknown_standard_length_raises(self):
        with pytest.raises(ValueError, match="Unknown standard_length"):
            compute_chain_params("cable", wire_gauge_mm=1.0, standard_length="necklace_99in")

    def test_alias_accepted(self):
        """'anchor' is an alias for 'mariner' and must not raise."""
        p = compute_chain_params("anchor", wire_gauge_mm=1.0, link_count=10)
        assert p["style"] == "mariner"


# ---------------------------------------------------------------------------
# compute_clasp_params
# ---------------------------------------------------------------------------

class TestComputeClaspParams:
    @pytest.mark.parametrize("style", sorted(_VALID_CLASP_STYLES))
    def test_all_clasps_produce_valid_spec(self, style):
        p = compute_clasp_params(style, wire_gauge_mm=1.0)
        assert p["op"] == "clasp"
        assert p["style"] == style
        assert p["wire_gauge_mm"] == pytest.approx(1.0)
        assert "clasp_hints" in p
        assert p["clasp_hints"]["type"] == style

    def test_lobster_clasp_body_dims(self):
        p = compute_clasp_params("lobster", wire_gauge_mm=1.0)
        hints = p["clasp_hints"]
        assert hints["body_length_mm"] > 0
        assert hints["body_width_mm"] > 0

    def test_spring_ring_outer_gt_inner(self):
        p = compute_clasp_params("spring_ring", wire_gauge_mm=1.0)
        hints = p["clasp_hints"]
        assert hints["outer_diameter_mm"] > hints["inner_diameter_mm"]

    def test_toggle_bar_longer_than_ring_id(self):
        p = compute_clasp_params("toggle", wire_gauge_mm=1.0)
        hints = p["clasp_hints"]
        assert hints["bar_length_mm"] > hints["ring_inner_diameter_mm"]

    def test_box_clasp_all_dims_positive(self):
        p = compute_clasp_params("box_clasp", wire_gauge_mm=1.0)
        hints = p["clasp_hints"]
        assert hints["box_length_mm"] > 0
        assert hints["box_width_mm"] > 0
        assert hints["box_height_mm"] > 0

    def test_unknown_clasp_raises(self):
        with pytest.raises(ValueError, match="Unknown clasp style"):
            compute_clasp_params("hook", wire_gauge_mm=1.0)

    def test_zero_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm must be > 0"):
            compute_clasp_params("lobster", wire_gauge_mm=0)


# ---------------------------------------------------------------------------
# Length ↔ link-count round-trips
# ---------------------------------------------------------------------------

class TestLengthLinkCountRoundTrip:
    """Round-trip: length → count → length should recover within one pitch."""

    @pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
    def test_round_trip_via_total_length(self, style):
        gauge = 1.0
        target_mm = 450.0
        p = compute_chain_params(style, wire_gauge_mm=gauge, total_length_mm=target_mm)
        pitch = p["link_pitch_mm"]
        # Recover length from link_count
        back_mm = link_count_to_chain_length(p["link_count"], pitch)
        # Should be within one pitch of the target
        assert abs(back_mm - target_mm) <= pitch + 1e-6, (
            f"style={style}: target={target_mm}, back={back_mm}, pitch={pitch}"
        )

    def test_direct_to_count(self):
        count = chain_length_to_link_count(total_length_mm=180.0, link_pitch_mm=3.0)
        assert count == 60

    def test_direct_to_length(self):
        length = link_count_to_chain_length(link_count=60, link_pitch_mm=3.0)
        assert length == pytest.approx(180.0)

    def test_round_trip_exact(self):
        pitch = 2.5
        n = 72
        length = link_count_to_chain_length(n, pitch)
        back_n = chain_length_to_link_count(length, pitch)
        assert back_n == n

    def test_chain_length_to_link_count_zero_length_raises(self):
        with pytest.raises(ValueError, match="total_length_mm must be > 0"):
            chain_length_to_link_count(0.0, 3.0)

    def test_chain_length_to_link_count_zero_pitch_raises(self):
        with pytest.raises(ValueError, match="link_pitch_mm must be > 0"):
            chain_length_to_link_count(180.0, 0.0)

    def test_link_count_to_chain_length_zero_count_raises(self):
        with pytest.raises(ValueError, match="link_count must be >= 1"):
            link_count_to_chain_length(0, 3.0)

    def test_link_count_to_chain_length_zero_pitch_raises(self):
        with pytest.raises(ValueError, match="link_pitch_mm must be > 0"):
            link_count_to_chain_length(10, 0.0)

    def test_minimum_count_is_one(self):
        """Very short total length should still yield at least 1 link."""
        count = chain_length_to_link_count(0.1, 100.0)
        assert count == 1


class TestStandardLengths:
    def test_bracelet_7in_is_177_8mm(self):
        assert _STANDARD_LENGTHS_MM["bracelet_7in"] == pytest.approx(177.8)

    def test_princess_18in_is_457_2mm(self):
        assert _STANDARD_LENGTHS_MM["princess_18in"] == pytest.approx(457.2)

    def test_bracelet_18cm_is_180mm(self):
        assert _STANDARD_LENGTHS_MM["bracelet_18cm"] == pytest.approx(180.0)

    def test_standard_length_names_sorted(self):
        names = standard_length_names()
        assert names == sorted(names)

    def test_all_standard_lengths_positive(self):
        for name, mm in _STANDARD_LENGTHS_MM.items():
            assert mm > 0, f"Standard length {name!r} = {mm} is not positive"


# ---------------------------------------------------------------------------
# link_pitch — per-style sanity checks
# ---------------------------------------------------------------------------

class TestLinkPitch:
    def test_cable_pitch_positive(self):
        p = link_pitch("cable", 3.5, 2.5, 1.0)
        assert p > 0

    def test_box_pitch_half_link_length(self):
        # Box pitch = max(link_length/2, wire_gauge*1.1)
        # With link_length=4.0, gauge=1.0: max(2.0, 1.1) = 2.0
        p = link_pitch("box", 4.0, 2.0, 1.0)
        assert p == pytest.approx(2.0)

    def test_pitch_never_less_than_gauge(self):
        for style in _VALID_LINK_STYLES:
            gauge = 1.0
            llen = gauge * 3.5
            lwid = gauge * 2.5
            p = link_pitch(style, llen, lwid, gauge)
            assert p >= gauge * 1.0, (
                f"style={style}: pitch={p} < gauge × 1.0"
            )


# ---------------------------------------------------------------------------
# ToolSpec declarations
# ---------------------------------------------------------------------------

class TestToolSpecs:
    def test_create_chain_spec_name(self):
        assert jewelry_create_chain_spec.name == "jewelry_create_chain"

    def test_create_chain_required_fields(self):
        req = set(jewelry_create_chain_spec.input_schema["required"])
        assert "file_id" in req
        assert "style" in req
        assert "wire_gauge_mm" in req

    def test_create_chain_style_enum_complete(self):
        props = jewelry_create_chain_spec.input_schema["properties"]
        assert set(props["style"]["enum"]) == _VALID_LINK_STYLES

    def test_create_chain_clasp_style_enum_complete(self):
        props = jewelry_create_chain_spec.input_schema["properties"]
        assert set(props["clasp_style"]["enum"]) == _VALID_CLASP_STYLES

    def test_chain_length_spec_name(self):
        assert jewelry_chain_length_spec.name == "jewelry_chain_length"

    def test_chain_length_required_fields(self):
        req = set(jewelry_chain_length_spec.input_schema["required"])
        assert "style" in req
        assert "wire_gauge_mm" in req

    def test_chain_length_style_enum_complete(self):
        props = jewelry_chain_length_spec.input_schema["properties"]
        assert set(props["style"]["enum"]) == _VALID_LINK_STYLES


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_chain — success paths
# ---------------------------------------------------------------------------

class TestCreateChainTool:
    def test_cable_bracelet_7in(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0,
                       standard_length="bracelet_7in")
        assert "error" not in r, r
        assert r["op"] == "chain_assembly"
        assert r["style"] == "cable"
        assert r["link_count"] >= 1
        assert r["total_length_mm"] > 0

    def test_node_appended_to_feature_doc(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, style="curb", wire_gauge_mm=1.2, link_count=60)
        doc = json.loads(store["content"])
        assert len(doc["features"]) == 1
        node = doc["features"][0]
        assert node["op"] == "chain_assembly"
        assert node["style"] == "curb"

    def test_node_id_starts_with_chain_assembly(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, style="box", wire_gauge_mm=1.5, link_count=50)
        doc = json.loads(store["content"])
        assert doc["features"][0]["id"].startswith("chain_assembly-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style="rope", wire_gauge_mm=0.8,
                       link_count=200, id="my-chain-1")
        assert "error" not in r
        assert r["id"] == "my-chain-1"

    def test_second_node_increments_id(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, style="cable", wire_gauge_mm=1.0, link_count=50)
        r2 = run_create(ctx, fid, style="mariner", wire_gauge_mm=1.0, link_count=30)
        assert "error" not in r2
        assert r2["id"] == "chain_assembly-2"

    @pytest.mark.parametrize("style", sorted(_VALID_LINK_STYLES))
    def test_all_styles_succeed(self, style):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style=style, wire_gauge_mm=1.0, link_count=50)
        assert "error" not in r, f"style={style!r}: {r}"

    def test_with_clasp_inline(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0,
                       standard_length="bracelet_7in", clasp_style="lobster")
        assert "error" not in r, r
        assert r["clasp"] == "lobster"
        doc = json.loads(store["content"])
        node = doc["features"][0]
        clasp = node.get("clasp")
        assert clasp is not None
        assert clasp["style"] == "lobster"
        assert clasp["op"] == "clasp"
        assert "clasp_hints" in clasp

    @pytest.mark.parametrize("clasp", sorted(_VALID_CLASP_STYLES))
    def test_all_clasps_inline(self, clasp):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0,
                       link_count=60, clasp_style=clasp)
        assert "error" not in r, f"clasp={clasp!r}: {r}"
        assert r["clasp"] == clasp

    def test_no_clasp_null_in_node(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, style="cable", wire_gauge_mm=1.0, link_count=50)
        doc = json.loads(store["content"])
        assert doc["features"][0]["clasp"] is None

    def test_total_length_mm_used(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style="figaro", wire_gauge_mm=1.0,
                       total_length_mm=180.0)
        assert "error" not in r
        assert r["link_count"] >= 1

    def test_diamond_cut_curb(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, style="curb", wire_gauge_mm=1.3,
                   link_count=60, diamond_cut=True)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["link_hints"]["diamond_cut"] is True

    def test_alias_anchor_stored_as_mariner(self):
        ctx, store, fid = make_ctx()
        r = run_create(ctx, fid, style="anchor", wire_gauge_mm=1.5, link_count=30)
        assert "error" not in r
        doc = json.loads(store["content"])
        assert doc["features"][0]["style"] == "mariner"

    def test_node_contains_all_spec_keys(self):
        ctx, store, fid = make_ctx()
        run_create(ctx, fid, style="byzantine", wire_gauge_mm=1.0, link_count=40)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        for key in ("op", "style", "wire_gauge_mm", "link_length_mm",
                    "link_width_mm", "link_count", "link_hints",
                    "total_length_mm", "link_pitch_mm", "open_ends", "clasp"):
            assert key in node, f"Missing key {key!r} in chain_assembly node"


# ---------------------------------------------------------------------------
# LLM tool: jewelry_create_chain — error paths
# ---------------------------------------------------------------------------

class TestCreateChainToolErrors:
    def test_missing_file_id(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_create_chain(
            ctx, json.dumps({"style": "cable", "wire_gauge_mm": 1.0,
                             "link_count": 50}).encode()
        ))
        assert "error" in r

    def test_missing_style(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, wire_gauge_mm=1.0, link_count=50)
        assert "error" in r

    def test_missing_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_sync(run_jewelry_create_chain(
            ctx, json.dumps({"file_id": str(fid), "style": "cable",
                             "link_count": 50}).encode()
        ))
        assert "error" in r

    def test_invalid_style(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="chain_mail", wire_gauge_mm=1.0, link_count=50)
        assert "error" in r

    def test_invalid_clasp_style(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0,
                       link_count=50, clasp_style="hook_and_eye")
        assert "error" in r

    def test_no_length_source(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0)
        assert "error" in r

    def test_two_length_sources(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0,
                       link_count=50, total_length_mm=200.0)
        assert "error" in r

    def test_invalid_file_id_uuid(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_create_chain(
            ctx, json.dumps({"file_id": "not-a-uuid", "style": "cable",
                             "wire_gauge_mm": 1.0, "link_count": 50}).encode()
        ))
        assert "error" in r

    def test_file_not_found(self):
        ctx, _, fid = make_ctx(kind="NOT_FOUND")
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0, link_count=50)
        assert "error" in r

    def test_zero_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=0, link_count=50)
        assert "error" in r

    def test_negative_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=-1.0, link_count=50)
        assert "error" in r

    def test_invalid_json(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_create_chain(ctx, b"not json!"))
        assert "error" in r

    def test_zero_link_count(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0, link_count=0)
        assert "error" in r

    def test_zero_total_length(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0, total_length_mm=0)
        assert "error" in r

    def test_unknown_standard_length(self):
        ctx, _, fid = make_ctx()
        r = run_create(ctx, fid, style="cable", wire_gauge_mm=1.0,
                       standard_length="necklace_99in")
        assert "error" in r


# ---------------------------------------------------------------------------
# LLM tool: jewelry_chain_length — success paths
# ---------------------------------------------------------------------------

class TestChainLengthTool:
    def test_standard_length_to_link_count(self):
        r = run_length(style="cable", wire_gauge_mm=1.0,
                       standard_length="bracelet_7in")
        assert "error" not in r, r
        assert r["link_count"] >= 1
        assert r["actual_total_length_mm"] > 0
        assert r["standard_length"] == "bracelet_7in"

    def test_total_length_to_link_count(self):
        r = run_length(style="curb", wire_gauge_mm=1.2, total_length_mm=457.2)
        assert "error" not in r, r
        assert r["link_count"] >= 1

    def test_link_count_to_length(self):
        r = run_length(style="box", wire_gauge_mm=1.5, link_count=100)
        assert "error" not in r, r
        assert r["total_length_mm"] > 0
        assert r["link_pitch_mm"] > 0

    def test_round_trip_via_tool(self):
        """length → count → length round-trip via the tool."""
        r1 = run_length(style="cable", wire_gauge_mm=1.0,
                        total_length_mm=180.0)
        assert "error" not in r1
        pitch = r1["link_pitch_mm"]
        count = r1["link_count"]
        r2 = run_length(style="cable", wire_gauge_mm=1.0,
                        link_count=count)
        assert "error" not in r2
        # Actual length should be within one pitch of target
        assert abs(r2["total_length_mm"] - 180.0) <= pitch + 1e-6


# ---------------------------------------------------------------------------
# LLM tool: jewelry_chain_length — error paths
# ---------------------------------------------------------------------------

class TestChainLengthToolErrors:
    def test_missing_style(self):
        r = run_length(wire_gauge_mm=1.0, link_count=50)
        assert "error" in r

    def test_missing_wire_gauge(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_chain_length(
            ctx, json.dumps({"style": "cable", "link_count": 50}).encode()
        ))
        assert "error" in r

    def test_invalid_style(self):
        r = run_length(style="chain_mail", wire_gauge_mm=1.0, link_count=50)
        assert "error" in r

    def test_no_length_source(self):
        r = run_length(style="cable", wire_gauge_mm=1.0)
        assert "error" in r

    def test_two_length_sources(self):
        r = run_length(style="cable", wire_gauge_mm=1.0,
                       link_count=50, total_length_mm=200.0)
        assert "error" in r

    def test_zero_wire_gauge(self):
        r = run_length(style="cable", wire_gauge_mm=0, link_count=50)
        assert "error" in r

    def test_negative_total_length(self):
        r = run_length(style="cable", wire_gauge_mm=1.0, total_length_mm=-10.0)
        assert "error" in r

    def test_zero_link_count(self):
        r = run_length(style="cable", wire_gauge_mm=1.0, link_count=0)
        assert "error" in r

    def test_unknown_standard_length(self):
        r = run_length(style="cable", wire_gauge_mm=1.0,
                       standard_length="necklace_99in")
        assert "error" in r

    def test_invalid_json(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_chain_length(ctx, b"bad json"))
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
    reason="pythonOCC not installed; skip chain OCC smoke tests"
)


@pytestmark_occ
class TestChainOCC:
    """Structural checks when OCC is present — confirm spec keys are enough
    for the occtWorker to build the geometry."""

    def test_chain_assembly_node_has_required_worker_keys(self):
        p = compute_chain_params("cable", wire_gauge_mm=1.0, link_count=50)
        required = {
            "style", "wire_gauge_mm", "link_length_mm", "link_width_mm",
            "link_count", "link_hints", "total_length_mm", "link_pitch_mm",
            "open_ends",
        }
        missing = required - set(p.keys())
        assert not missing, f"Missing keys for worker: {missing}"

    def test_mariner_central_bar_spec(self):
        p = compute_chain_params("mariner", wire_gauge_mm=1.5, link_count=30)
        hints = p["link_hints"]
        assert hints["central_bar"] is True
        assert hints["central_bar_width_mm"] > 0
        assert hints["central_bar_diameter_mm"] > 0

    def test_snake_scale_wider_than_wire(self):
        p = compute_chain_params("snake", wire_gauge_mm=1.0, link_count=40)
        hints = p["link_hints"]
        assert hints["scale_width_mm"] > 1.0  # wider than wire gauge

    def test_byzantine_cluster_links_count(self):
        p = compute_chain_params("byzantine", wire_gauge_mm=0.9, link_count=60)
        hints = p["link_hints"]
        assert hints["cluster_links"] == 4
