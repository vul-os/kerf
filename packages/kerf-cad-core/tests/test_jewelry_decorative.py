"""
Tests for kerf_cad_core.jewelry.decorative

Pure-Python section (always runs):
  - compute_milgrain_params: valid spec, target_ref required, bad inputs rejected
  - compute_beading_params: all patterns, validation
  - compute_filigree_params: all motifs, validation
  - compute_twisted_wire_params: braid patterns, strand validation
  - compute_scrollwork_params: all styles, depth clamp, validation
  - compute_surface_texture_params: all texture types, intensity bounds
  - LLM tool specs: names, required fields, enum coverage
  - LLM tool runners (all 6): success paths, node shape, target_ref missing,
    bad file_id, validation errors, missing required fields
  - node-spec schema: op="decorative_apply", feature=<name>, target_ref, decorative_hints
  - node id auto-increments correctly

OCC-gated section:
  - Skipped cleanly when pythonOCC is absent.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.jewelry.decorative import (
    # constants
    _VALID_MILGRAIN_PROFILES,
    _VALID_BEADING_PATTERNS,
    _VALID_BEADING_GRAIN_SHAPES,
    _VALID_FILIGREE_MOTIFS,
    _VALID_BRAID_PATTERNS,
    _VALID_SCROLLWORK_STYLES,
    _VALID_TEXTURE_TYPES,
    # compute functions
    compute_milgrain_params,
    compute_beading_params,
    compute_filigree_params,
    compute_twisted_wire_params,
    compute_scrollwork_params,
    compute_surface_texture_params,
    # tool specs
    jewelry_apply_milgrain_spec,
    jewelry_apply_beading_spec,
    jewelry_apply_filigree_spec,
    jewelry_apply_twisted_wire_spec,
    jewelry_apply_scrollwork_spec,
    jewelry_apply_surface_texture_spec,
    # runners
    run_jewelry_apply_milgrain,
    run_jewelry_apply_beading,
    run_jewelry_apply_filigree,
    run_jewelry_apply_twisted_wire,
    run_jewelry_apply_scrollwork,
    run_jewelry_apply_surface_texture,
    # constants
    _OP,
)


# ---------------------------------------------------------------------------
# Test helpers
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


def call_tool(runner, ctx, file_id, **kwargs):
    args = {"file_id": str(file_id), **kwargs}
    return run_sync(runner(ctx, json.dumps(args).encode()))


_TARGET = "edge-001"


# ---------------------------------------------------------------------------
# Shared node-spec contract helper
# ---------------------------------------------------------------------------

def assert_node_spec(spec: dict, expected_feature: str) -> None:
    """Assert the common node-spec contract for decorative ops."""
    assert spec["op"] == _OP, f"expected op='{_OP}', got {spec['op']!r}"
    assert spec["feature"] == expected_feature
    assert "target_ref" in spec
    assert spec["target_ref"], "target_ref must not be empty"
    assert "decorative_hints" in spec
    assert isinstance(spec["decorative_hints"], dict)


# ===========================================================================
# 1. Milgrain
# ===========================================================================

class TestMilgrainParams:
    def test_basic_valid_spec(self):
        s = compute_milgrain_params(_TARGET, 0.7, 0.9)
        assert_node_spec(s, "milgrain")
        h = s["decorative_hints"]
        assert h["bead_diameter_mm"] == pytest.approx(0.7)
        assert h["pitch_mm"] == pytest.approx(0.9)
        assert h["profile"] == "round"
        assert h["offset_mm"] == pytest.approx(0.0)

    @pytest.mark.parametrize("profile", sorted(_VALID_MILGRAIN_PROFILES))
    def test_all_profiles(self, profile):
        s = compute_milgrain_params(_TARGET, 0.5, 0.6, profile=profile)
        assert s["decorative_hints"]["profile"] == profile

    def test_target_ref_stored(self):
        s = compute_milgrain_params("my-edge-42", 0.5, 0.7)
        assert s["target_ref"] == "my-edge-42"

    def test_target_ref_missing_raises(self):
        with pytest.raises(ValueError, match="target_ref is required"):
            compute_milgrain_params("", 0.5, 0.7)

    def test_target_ref_none_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            compute_milgrain_params(None, 0.5, 0.7)  # type: ignore[arg-type]

    def test_zero_bead_diameter_raises(self):
        with pytest.raises(ValueError, match="bead_diameter_mm must be > 0"):
            compute_milgrain_params(_TARGET, 0.0, 0.7)

    def test_negative_bead_diameter_raises(self):
        with pytest.raises(ValueError, match="bead_diameter_mm must be > 0"):
            compute_milgrain_params(_TARGET, -0.5, 0.7)

    def test_zero_pitch_raises(self):
        with pytest.raises(ValueError, match="pitch_mm must be > 0"):
            compute_milgrain_params(_TARGET, 0.5, 0.0)

    def test_invalid_profile_raises(self):
        with pytest.raises(ValueError, match="is not valid"):
            compute_milgrain_params(_TARGET, 0.5, 0.7, profile="triangular")

    def test_offset_stored(self):
        s = compute_milgrain_params(_TARGET, 0.5, 0.7, offset_mm=0.2)
        assert s["decorative_hints"]["offset_mm"] == pytest.approx(0.2)

    def test_pitch_smaller_than_bead_allowed(self):
        # Tight milgrain — overlapping beads are allowed; worker clamps
        s = compute_milgrain_params(_TARGET, 0.8, 0.5)
        assert s["decorative_hints"]["pitch_mm"] == pytest.approx(0.5)


class TestMilgrainTool:
    def test_success_returns_ok(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_milgrain, ctx, fid,
                      target_ref=_TARGET, bead_diameter_mm=0.7, pitch_mm=0.9)
        assert "error" not in r, r
        assert r["op"] == _OP
        assert r["feature"] == "milgrain"
        assert r["target_ref"] == _TARGET

    def test_node_id_assigned(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_milgrain, ctx, fid,
                      target_ref=_TARGET, bead_diameter_mm=0.7, pitch_mm=0.9)
        assert r["id"].startswith("milgrain-")

    def test_missing_file_id(self):
        ctx, _, _ = make_ctx()
        r = run_sync(run_jewelry_apply_milgrain(ctx, json.dumps({
            "target_ref": _TARGET, "bead_diameter_mm": 0.7, "pitch_mm": 0.9,
        }).encode()))
        assert "error" in r

    def test_bad_file_id(self):
        ctx, _, _ = make_ctx()
        r = call_tool(run_jewelry_apply_milgrain, ctx, "not-a-uuid",
                      target_ref=_TARGET, bead_diameter_mm=0.7, pitch_mm=0.9)
        assert "error" in r

    def test_missing_target_ref_validation_error(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_milgrain, ctx, fid,
                      target_ref="", bead_diameter_mm=0.7, pitch_mm=0.9)
        assert "error" in r

    def test_missing_bead_diameter(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_milgrain, ctx, fid,
                      target_ref=_TARGET, pitch_mm=0.9)
        assert "error" in r

    def test_file_not_found(self):
        ctx, store, fid = make_ctx(kind="NOT_FOUND")
        r = call_tool(run_jewelry_apply_milgrain, ctx, fid,
                      target_ref=_TARGET, bead_diameter_mm=0.7, pitch_mm=0.9)
        assert "error" in r


# ===========================================================================
# 2. Beading
# ===========================================================================

class TestBeadingParams:
    def test_basic_valid_spec(self):
        s = compute_beading_params(_TARGET, 0.6)
        assert_node_spec(s, "beading")
        h = s["decorative_hints"]
        assert h["grain_diameter_mm"] == pytest.approx(0.6)
        assert h["pattern"] == "hex"
        assert h["grain_shape"] == "hemisphere"

    @pytest.mark.parametrize("pattern", sorted(_VALID_BEADING_PATTERNS))
    def test_all_patterns(self, pattern):
        kw = {"row_count": 3, "col_count": 3} if pattern in ("grid", "hex") else {"density": 0.5}
        s = compute_beading_params(_TARGET, 0.5, pattern=pattern, **kw)
        assert s["decorative_hints"]["pattern"] == pattern

    @pytest.mark.parametrize("grain_shape", sorted(_VALID_BEADING_GRAIN_SHAPES))
    def test_all_grain_shapes(self, grain_shape):
        s = compute_beading_params(_TARGET, 0.5, grain_shape=grain_shape)
        assert s["decorative_hints"]["grain_shape"] == grain_shape

    def test_seat_depth_computed(self):
        s = compute_beading_params(_TARGET, 1.0, seat_depth_fraction=0.5)
        assert s["decorative_hints"]["seat_depth_mm"] == pytest.approx(0.5)

    def test_seat_depth_fraction_zero_raises(self):
        with pytest.raises(ValueError, match="seat_depth_fraction"):
            compute_beading_params(_TARGET, 0.5, seat_depth_fraction=0.0)

    def test_seat_depth_fraction_above_one_raises(self):
        with pytest.raises(ValueError, match="seat_depth_fraction"):
            compute_beading_params(_TARGET, 0.5, seat_depth_fraction=1.5)

    def test_zero_grain_diameter_raises(self):
        with pytest.raises(ValueError, match="grain_diameter_mm"):
            compute_beading_params(_TARGET, 0.0)

    def test_target_ref_missing_raises(self):
        with pytest.raises(ValueError, match="target_ref"):
            compute_beading_params("", 0.5)

    def test_random_layout_has_seed(self):
        s = compute_beading_params(_TARGET, 0.5, pattern="random", density=2.0, random_seed=123)
        h = s["decorative_hints"]
        assert h["random_seed"] == 123
        assert "density_per_mm2" in h

    def test_hex_layout_hint(self):
        s = compute_beading_params(_TARGET, 0.5, pattern="hex", row_count=3, col_count=3)
        assert s["decorative_hints"]["layout"] == "offset_rows"

    def test_invalid_pattern_raises(self):
        with pytest.raises(ValueError, match="is not valid"):
            compute_beading_params(_TARGET, 0.5, pattern="diagonal")


class TestBeadingTool:
    def test_success(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_beading, ctx, fid,
                      target_ref=_TARGET, grain_diameter_mm=0.6)
        assert "error" not in r, r
        assert r["feature"] == "beading"

    def test_missing_grain_diameter(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_beading, ctx, fid, target_ref=_TARGET)
        assert "error" in r

    def test_missing_target_ref(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_beading, ctx, fid,
                      target_ref="", grain_diameter_mm=0.6)
        assert "error" in r


# ===========================================================================
# 3. Filigree
# ===========================================================================

class TestFiligreParams:
    def test_basic_valid_spec(self):
        s = compute_filigree_params(_TARGET)
        assert_node_spec(s, "filigree")
        h = s["decorative_hints"]
        assert h["motif"] == "scroll"
        assert h["fill"] is True

    @pytest.mark.parametrize("motif", sorted(_VALID_FILIGREE_MOTIFS))
    def test_all_motifs(self, motif):
        s = compute_filigree_params(_TARGET, motif=motif)
        assert s["decorative_hints"]["motif"] == motif

    def test_target_ref_missing_raises(self):
        with pytest.raises(ValueError, match="target_ref"):
            compute_filigree_params("")

    def test_zero_scale_raises(self):
        with pytest.raises(ValueError, match="scale"):
            compute_filigree_params(_TARGET, scale=0.0)

    def test_zero_density_raises(self):
        with pytest.raises(ValueError, match="density"):
            compute_filigree_params(_TARGET, density=0.0)

    def test_zero_wire_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm"):
            compute_filigree_params(_TARGET, wire_gauge_mm=0.0)

    def test_unrealistic_wire_gauge_raises(self):
        with pytest.raises(ValueError, match="unrealistically large"):
            compute_filigree_params(_TARGET, wire_gauge_mm=10.0)

    def test_invalid_motif_raises(self):
        with pytest.raises(ValueError, match="is not valid"):
            compute_filigree_params(_TARGET, motif="baroque")

    def test_fill_false_stored(self):
        s = compute_filigree_params(_TARGET, fill=False)
        assert s["decorative_hints"]["fill"] is False


class TestFiligréTool:
    def test_success(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_filigree, ctx, fid, target_ref=_TARGET)
        assert "error" not in r, r
        assert r["feature"] == "filigree"

    def test_missing_target_ref(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_filigree, ctx, fid, target_ref="")
        assert "error" in r

    def test_bad_motif_rejected(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_filigree, ctx, fid,
                      target_ref=_TARGET, motif="baroque")
        assert "error" in r


# ===========================================================================
# 4. Twisted wire
# ===========================================================================

class TestTwistedWireParams:
    def test_basic_valid_spec(self):
        s = compute_twisted_wire_params(_TARGET, 3, 0.6, 3.0)
        assert_node_spec(s, "twisted_wire")
        h = s["decorative_hints"]
        assert h["strand_count"] == 3
        assert h["wire_gauge_mm"] == pytest.approx(0.6)
        assert h["twist_pitch_mm"] == pytest.approx(3.0)
        assert "bundle_diameter_mm" in h

    @pytest.mark.parametrize("braid", sorted(_VALID_BRAID_PATTERNS))
    def test_all_braid_patterns(self, braid):
        s = compute_twisted_wire_params(_TARGET, 3, 0.6, 3.0, braid_pattern=braid)
        assert s["decorative_hints"]["braid_pattern"] == braid

    def test_target_ref_missing_raises(self):
        with pytest.raises(ValueError, match="target_ref"):
            compute_twisted_wire_params("", 3, 0.6, 3.0)

    def test_strand_count_one_raises(self):
        with pytest.raises(ValueError, match="strand_count must be an integer >= 2"):
            compute_twisted_wire_params(_TARGET, 1, 0.6, 3.0)

    def test_strand_count_zero_raises(self):
        with pytest.raises(ValueError, match="strand_count"):
            compute_twisted_wire_params(_TARGET, 0, 0.6, 3.0)

    def test_zero_wire_gauge_raises(self):
        with pytest.raises(ValueError, match="wire_gauge_mm"):
            compute_twisted_wire_params(_TARGET, 3, 0.0, 3.0)

    def test_unrealistic_wire_gauge_raises(self):
        with pytest.raises(ValueError, match="unrealistically large"):
            compute_twisted_wire_params(_TARGET, 3, 15.0, 3.0)

    def test_zero_twist_pitch_raises(self):
        with pytest.raises(ValueError, match="twist_pitch_mm"):
            compute_twisted_wire_params(_TARGET, 3, 0.6, 0.0)

    def test_invalid_braid_pattern_raises(self):
        with pytest.raises(ValueError, match="is not valid"):
            compute_twisted_wire_params(_TARGET, 3, 0.6, 3.0, braid_pattern="chain")

    def test_bundle_diameter_increases_with_strand_count(self):
        s2 = compute_twisted_wire_params(_TARGET, 2, 0.5, 2.0)
        s4 = compute_twisted_wire_params(_TARGET, 4, 0.5, 2.0)
        assert s4["decorative_hints"]["bundle_diameter_mm"] > s2["decorative_hints"]["bundle_diameter_mm"]


class TestTwistedWireTool:
    def test_success(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_twisted_wire, ctx, fid,
                      target_ref=_TARGET, strand_count=3,
                      wire_gauge_mm=0.6, twist_pitch_mm=3.0)
        assert "error" not in r, r
        assert r["feature"] == "twisted_wire"

    def test_missing_strand_count(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_twisted_wire, ctx, fid,
                      target_ref=_TARGET, wire_gauge_mm=0.6, twist_pitch_mm=3.0)
        assert "error" in r

    def test_missing_wire_gauge(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_twisted_wire, ctx, fid,
                      target_ref=_TARGET, strand_count=3, twist_pitch_mm=3.0)
        assert "error" in r

    def test_missing_twist_pitch(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_twisted_wire, ctx, fid,
                      target_ref=_TARGET, strand_count=3, wire_gauge_mm=0.6)
        assert "error" in r

    def test_missing_target_ref(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_twisted_wire, ctx, fid,
                      target_ref="", strand_count=3,
                      wire_gauge_mm=0.6, twist_pitch_mm=3.0)
        assert "error" in r


# ===========================================================================
# 5. Scrollwork
# ===========================================================================

class TestScrollworkParams:
    def test_basic_valid_spec(self):
        s = compute_scrollwork_params(_TARGET, "scallop", 0.3, 2.0)
        assert_node_spec(s, "scrollwork")
        h = s["decorative_hints"]
        assert h["style"] == "scallop"
        assert h["relief_depth_mm"] == pytest.approx(0.3)
        assert h["pitch_mm"] == pytest.approx(2.0)
        assert h["mirror"] is True

    @pytest.mark.parametrize("style", sorted(_VALID_SCROLLWORK_STYLES))
    def test_all_styles(self, style):
        s = compute_scrollwork_params(_TARGET, style, 0.3, 2.0)
        assert s["decorative_hints"]["style"] == style

    def test_target_ref_missing_raises(self):
        with pytest.raises(ValueError, match="target_ref"):
            compute_scrollwork_params("", "scallop", 0.3, 2.0)

    def test_zero_relief_depth_raises(self):
        with pytest.raises(ValueError, match="relief_depth_mm"):
            compute_scrollwork_params(_TARGET, "scallop", 0.0, 2.0)

    def test_too_deep_relief_raises(self):
        with pytest.raises(ValueError, match="unrealistically deep"):
            compute_scrollwork_params(_TARGET, "scallop", 6.0, 2.0)

    def test_zero_pitch_raises(self):
        with pytest.raises(ValueError, match="pitch_mm"):
            compute_scrollwork_params(_TARGET, "scallop", 0.3, 0.0)

    def test_invalid_style_raises(self):
        with pytest.raises(ValueError, match="is not valid"):
            compute_scrollwork_params(_TARGET, "greek_key", 0.3, 2.0)

    def test_mirror_false_stored(self):
        s = compute_scrollwork_params(_TARGET, "scroll", 0.3, 2.0, mirror=False)
        assert s["decorative_hints"]["mirror"] is False


class TestScrollworkTool:
    def test_success(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_scrollwork, ctx, fid,
                      target_ref=_TARGET, style="leaf",
                      relief_depth_mm=0.4, pitch_mm=2.5)
        assert "error" not in r, r
        assert r["feature"] == "scrollwork"

    def test_missing_style(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_scrollwork, ctx, fid,
                      target_ref=_TARGET, relief_depth_mm=0.4, pitch_mm=2.5)
        assert "error" in r

    def test_missing_target_ref(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_scrollwork, ctx, fid,
                      target_ref="", style="scallop",
                      relief_depth_mm=0.3, pitch_mm=2.0)
        assert "error" in r

    def test_bad_style_rejected(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_scrollwork, ctx, fid,
                      target_ref=_TARGET, style="greek_key",
                      relief_depth_mm=0.3, pitch_mm=2.0)
        assert "error" in r


# ===========================================================================
# 6. Surface texture
# ===========================================================================

class TestSurfaceTextureParams:
    def test_basic_valid_spec(self):
        s = compute_surface_texture_params(_TARGET, "hammered")
        assert_node_spec(s, "surface_texture")
        h = s["decorative_hints"]
        assert h["texture_type"] == "hammered"
        assert h["intensity"] == pytest.approx(0.7)

    @pytest.mark.parametrize("texture_type", sorted(_VALID_TEXTURE_TYPES))
    def test_all_texture_types(self, texture_type):
        s = compute_surface_texture_params(_TARGET, texture_type)
        assert s["decorative_hints"]["texture_type"] == texture_type

    def test_target_ref_missing_raises(self):
        with pytest.raises(ValueError, match="target_ref"):
            compute_surface_texture_params("", "hammered")

    def test_zero_intensity_raises(self):
        with pytest.raises(ValueError, match="intensity"):
            compute_surface_texture_params(_TARGET, "hammered", intensity=0.0)

    def test_intensity_above_one_raises(self):
        with pytest.raises(ValueError, match="intensity"):
            compute_surface_texture_params(_TARGET, "hammered", intensity=1.5)

    def test_invalid_texture_type_raises(self):
        with pytest.raises(ValueError, match="is not valid"):
            compute_surface_texture_params(_TARGET, "brushed")

    def test_florentine_has_direction(self):
        s = compute_surface_texture_params(_TARGET, "florentine", direction_deg=45.0)
        assert s["decorative_hints"]["direction_deg"] == pytest.approx(45.0)
        assert "line_family_count" in s["decorative_hints"]

    def test_satin_has_direction(self):
        s = compute_surface_texture_params(_TARGET, "satin", direction_deg=90.0)
        assert "direction_deg" in s["decorative_hints"]
        assert "scratch_depth_relative" in s["decorative_hints"]

    def test_hammered_no_direction_key(self):
        s = compute_surface_texture_params(_TARGET, "hammered")
        # hammered is non-directional
        assert "direction_deg" not in s["decorative_hints"]

    def test_sandblast_matte_flag(self):
        s = compute_surface_texture_params(_TARGET, "sandblast")
        assert s["decorative_hints"]["matte"] is True

    def test_direction_normalised_to_360(self):
        s = compute_surface_texture_params(_TARGET, "satin", direction_deg=450.0)
        assert s["decorative_hints"]["direction_deg"] == pytest.approx(90.0)

    def test_hammered_facet_distribution(self):
        s = compute_surface_texture_params(_TARGET, "hammered")
        assert s["decorative_hints"]["facet_distribution"] == "random"


class TestSurfaceTextureTool:
    def test_success(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_surface_texture, ctx, fid,
                      target_ref=_TARGET, texture_type="satin")
        assert "error" not in r, r
        assert r["feature"] == "surface_texture"
        assert r["texture_type"] == "satin"

    def test_missing_texture_type(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_surface_texture, ctx, fid,
                      target_ref=_TARGET)
        assert "error" in r

    def test_missing_target_ref(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_surface_texture, ctx, fid,
                      target_ref="", texture_type="hammered")
        assert "error" in r

    def test_bad_texture_type_rejected(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_surface_texture, ctx, fid,
                      target_ref=_TARGET, texture_type="brushed")
        assert "error" in r

    def test_invalid_intensity_rejected(self):
        ctx, _, fid = make_ctx()
        r = call_tool(run_jewelry_apply_surface_texture, ctx, fid,
                      target_ref=_TARGET, texture_type="hammered", intensity=2.0)
        assert "error" in r


# ===========================================================================
# Tool spec contract (names, required fields, enum coverage)
# ===========================================================================

class TestToolSpecs:
    def test_milgrain_spec_name(self):
        assert jewelry_apply_milgrain_spec.name == "jewelry_apply_milgrain"

    def test_beading_spec_name(self):
        assert jewelry_apply_beading_spec.name == "jewelry_apply_beading"

    def test_filigree_spec_name(self):
        assert jewelry_apply_filigree_spec.name == "jewelry_apply_filigree"

    def test_twisted_wire_spec_name(self):
        assert jewelry_apply_twisted_wire_spec.name == "jewelry_apply_twisted_wire"

    def test_scrollwork_spec_name(self):
        assert jewelry_apply_scrollwork_spec.name == "jewelry_apply_scrollwork"

    def test_surface_texture_spec_name(self):
        assert jewelry_apply_surface_texture_spec.name == "jewelry_apply_surface_texture"

    def test_milgrain_required_fields(self):
        required = jewelry_apply_milgrain_spec.input_schema["required"]
        assert "file_id" in required
        assert "target_ref" in required
        assert "bead_diameter_mm" in required
        assert "pitch_mm" in required

    def test_beading_required_fields(self):
        required = jewelry_apply_beading_spec.input_schema["required"]
        assert "file_id" in required
        assert "target_ref" in required
        assert "grain_diameter_mm" in required

    def test_filigree_required_fields(self):
        required = jewelry_apply_filigree_spec.input_schema["required"]
        assert "file_id" in required
        assert "target_ref" in required

    def test_twisted_wire_required_fields(self):
        required = jewelry_apply_twisted_wire_spec.input_schema["required"]
        assert "target_ref" in required
        assert "strand_count" in required
        assert "wire_gauge_mm" in required
        assert "twist_pitch_mm" in required

    def test_scrollwork_required_fields(self):
        required = jewelry_apply_scrollwork_spec.input_schema["required"]
        assert "target_ref" in required
        assert "style" in required
        assert "relief_depth_mm" in required
        assert "pitch_mm" in required

    def test_surface_texture_required_fields(self):
        required = jewelry_apply_surface_texture_spec.input_schema["required"]
        assert "target_ref" in required
        assert "texture_type" in required

    def test_milgrain_profile_enum_matches_valid_set(self):
        enum = set(
            jewelry_apply_milgrain_spec.input_schema["properties"]["profile"]["enum"]
        )
        assert enum == _VALID_MILGRAIN_PROFILES

    def test_beading_pattern_enum_matches_valid_set(self):
        enum = set(
            jewelry_apply_beading_spec.input_schema["properties"]["pattern"]["enum"]
        )
        assert enum == _VALID_BEADING_PATTERNS

    def test_filigree_motif_enum_matches_valid_set(self):
        enum = set(
            jewelry_apply_filigree_spec.input_schema["properties"]["motif"]["enum"]
        )
        assert enum == _VALID_FILIGREE_MOTIFS

    def test_twisted_wire_braid_enum_matches_valid_set(self):
        enum = set(
            jewelry_apply_twisted_wire_spec.input_schema["properties"]["braid_pattern"]["enum"]
        )
        assert enum == _VALID_BRAID_PATTERNS

    def test_scrollwork_style_enum_matches_valid_set(self):
        enum = set(
            jewelry_apply_scrollwork_spec.input_schema["properties"]["style"]["enum"]
        )
        assert enum == _VALID_SCROLLWORK_STYLES

    def test_surface_texture_enum_matches_valid_set(self):
        enum = set(
            jewelry_apply_surface_texture_spec.input_schema["properties"]["texture_type"]["enum"]
        )
        assert enum == _VALID_TEXTURE_TYPES


# ===========================================================================
# Node id auto-increment
# ===========================================================================

class TestNodeIdIncrement:
    def _append_and_get_id(self, runner, ctx, fid, **kwargs):
        r = call_tool(runner, ctx, fid, **kwargs)
        assert "error" not in r, r
        return r["id"]

    def test_milgrain_increments(self):
        ctx, _, fid = make_ctx()
        id1 = self._append_and_get_id(
            run_jewelry_apply_milgrain, ctx, fid,
            target_ref=_TARGET, bead_diameter_mm=0.7, pitch_mm=0.9
        )
        id2 = self._append_and_get_id(
            run_jewelry_apply_milgrain, ctx, fid,
            target_ref="edge-002", bead_diameter_mm=0.5, pitch_mm=0.6
        )
        n1 = int(id1.split("-")[-1])
        n2 = int(id2.split("-")[-1])
        assert n2 > n1

    def test_surface_texture_increments(self):
        ctx, _, fid = make_ctx()
        id1 = self._append_and_get_id(
            run_jewelry_apply_surface_texture, ctx, fid,
            target_ref=_TARGET, texture_type="satin"
        )
        id2 = self._append_and_get_id(
            run_jewelry_apply_surface_texture, ctx, fid,
            target_ref="face-002", texture_type="hammered"
        )
        n1 = int(id1.split("-")[-1])
        n2 = int(id2.split("-")[-1])
        assert n2 > n1


# ===========================================================================
# OCC-gated section
# ===========================================================================

try:
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # type: ignore[import]
    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False


@pytest.mark.skipif(not _OCC_AVAILABLE, reason="pythonOCC not installed — OCC-gated tests skipped")
class TestOCCGated:
    """Placeholder for future OCCT evaluation tests.

    When ``opDecorativeApply`` is wired in the occtWorker, add integration
    tests here that tessellate the node-specs against a real solid.
    Currently the worker stub is not connected (FeatureView deferred).
    """

    def test_occ_import_succeeds(self):
        # If we get here, pythonOCC is available.
        assert _OCC_AVAILABLE
