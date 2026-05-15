"""
Tests for kerf_cad_core.jewelry.ring

Pure-Python section (always runs):
  - ring_size_to_diameter: US, UK/AU, EU, JP forward lookup
  - ring_diameter_to_size: round-trip inverse
  - compute_shank_params: profile/shoulder validation, geometry output
  - LLM tool runners: jewelry_ring_size_to_diameter, jewelry_create_ring_shank
    (using in-memory fake pool/ctx, same pattern as test_feature_sweep1_mode.py)

OCC-gated section:
  - Skipped cleanly when pythonocc absent (checks _OCC_AVAILABLE flag).
  - When OCC present: validates that a ring_shank node can be evaluated by
    the worker (structural smoke test only — full sweep tested in occtWorker
    JS tests).
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.jewelry.ring import (
    _UK_AU_SIZES,
    _JP_SIZES,
    _VALID_PROFILES,
    _VALID_SHOULDER_STYLES,
    _VALID_SYSTEMS,
    _id_mm_to_circumference,
    _validate_width_profile,
    compute_shank_params,
    jewelry_create_ring_shank_spec,
    jewelry_ring_size_to_diameter_spec,
    ring_diameter_to_size,
    ring_size_to_diameter,
    run_jewelry_create_ring_shank,
    run_jewelry_ring_size_to_diameter,
    EngravingSpec,
    SizingBeadSpec,
)

_PI = math.pi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ctx(initial_content: str = ""):
    """Return (ctx, store, file_id) with an in-memory fake pool."""
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
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    except ImportError:
        # Minimal stub when kerf_core is not installed in the test env.
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


def run_tool_sync(coro):
    loop = asyncio.new_event_loop()
    try:
        return json.loads(loop.run_until_complete(coro))
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# US ring-size forward lookups
# ---------------------------------------------------------------------------

class TestUSForward:
    def test_us7_approx_17_3mm(self):
        """US 7 should be ≈17.32 mm per the industry formula."""
        d = ring_size_to_diameter("us", 7)
        assert abs(d - 17.3196) < 0.001, f"US 7 expected ≈17.32 mm, got {d}"

    def test_us0_intercept(self):
        """US 0 → exactly intercept value 11.63 mm."""
        d = ring_size_to_diameter("us", 0)
        assert abs(d - 11.63) < 1e-9

    def test_us16_max(self):
        """US 16 → 11.63 + 0.8128×16 = 24.6348 mm."""
        expected = 11.63 + 0.8128 * 16
        d = ring_size_to_diameter("us", 16)
        assert abs(d - expected) < 1e-9

    def test_us_half_size_string(self):
        """US '7½' should equal US 7.5."""
        d_str = ring_size_to_diameter("us", "7½")
        d_float = ring_size_to_diameter("us", 7.5)
        assert abs(d_str - d_float) < 1e-9

    def test_us_half_size_decimal(self):
        d = ring_size_to_diameter("us", 6.5)
        expected = 11.63 + 0.8128 * 6.5
        assert abs(d - expected) < 1e-9

    def test_us_out_of_range_raises(self):
        with pytest.raises(ValueError, match="0–16"):
            ring_size_to_diameter("us", 17)

    def test_us_negative_raises(self):
        with pytest.raises(ValueError, match="0–16"):
            ring_size_to_diameter("us", -0.5)

    def test_us_circumference_us7(self):
        """US 7 circumference should be close to published 54.44 mm."""
        d = ring_size_to_diameter("us", 7)
        c = _id_mm_to_circumference(d)
        assert abs(c - 54.44) < 0.1, f"Circumference for US 7 expected ≈54.44 mm, got {c}"

    def test_us_case_insensitive(self):
        d1 = ring_size_to_diameter("US", 7)
        d2 = ring_size_to_diameter("us", 7)
        assert d1 == d2

    def test_us10_approx_19_76mm(self):
        d = ring_size_to_diameter("us", 10)
        assert abs(d - 19.76) < 0.01


# ---------------------------------------------------------------------------
# UK / AU ring-size forward lookups
# ---------------------------------------------------------------------------

class TestUKAUForward:
    def test_uk_n(self):
        """UK N → circumference 54.4 mm → ID ≈ 17.32 mm."""
        d = ring_size_to_diameter("uk", "N")
        expected = 54.4 / _PI
        assert abs(d - expected) < 0.01

    def test_au_n_same_as_uk(self):
        d_uk = ring_size_to_diameter("uk", "N")
        d_au = ring_size_to_diameter("au", "N")
        assert abs(d_uk - d_au) < 1e-9

    def test_uk_half_size(self):
        d = ring_size_to_diameter("uk", "N½")
        expected = _UK_AU_SIZES["N½"] / _PI
        assert abs(d - expected) < 1e-9

    def test_uk_z_plus_1(self):
        d = ring_size_to_diameter("uk", "Z+1")
        expected = _UK_AU_SIZES["Z+1"] / _PI
        assert abs(d - expected) < 1e-9

    def test_uk_unknown_raises(self):
        with pytest.raises(ValueError):
            ring_size_to_diameter("uk", "ZZZ")

    def test_uk_lowercase_normalised(self):
        """Lowercase 'n' should be accepted and equal 'N'."""
        d_lower = ring_size_to_diameter("uk", "n")
        d_upper = ring_size_to_diameter("uk", "N")
        assert abs(d_lower - d_upper) < 1e-9


# ---------------------------------------------------------------------------
# EU ring-size forward lookups
# ---------------------------------------------------------------------------

class TestEUForward:
    def test_eu_54(self):
        d = ring_size_to_diameter("eu", 54)
        expected = 54.0 / _PI
        assert abs(d - expected) < 1e-9

    def test_eu_out_of_range_low(self):
        with pytest.raises(ValueError, match="41"):
            ring_size_to_diameter("eu", 40)

    def test_eu_out_of_range_high(self):
        with pytest.raises(ValueError, match="76"):
            ring_size_to_diameter("eu", 77)

    def test_eu_string_number(self):
        d = ring_size_to_diameter("eu", "54")
        expected = 54.0 / _PI
        assert abs(d - expected) < 1e-9

    def test_eu_float(self):
        d = ring_size_to_diameter("eu", 54.5)
        expected = 54.5 / _PI
        assert abs(d - expected) < 1e-9


# ---------------------------------------------------------------------------
# JP ring-size forward lookups
# ---------------------------------------------------------------------------

class TestJPForward:
    def test_jp_13(self):
        d = ring_size_to_diameter("jp", 13)
        expected = _JP_SIZES[13] / _PI
        assert abs(d - expected) < 1e-9

    def test_jp_1(self):
        d = ring_size_to_diameter("jp", 1)
        expected = _JP_SIZES[1] / _PI
        assert abs(d - expected) < 1e-9

    def test_jp_30(self):
        d = ring_size_to_diameter("jp", 30)
        expected = _JP_SIZES[30] / _PI
        assert abs(d - expected) < 1e-9

    def test_jp_out_of_range(self):
        with pytest.raises(ValueError, match="1–30"):
            ring_size_to_diameter("jp", 31)

    def test_jp_zero_raises(self):
        with pytest.raises(ValueError, match="1–30"):
            ring_size_to_diameter("jp", 0)


# ---------------------------------------------------------------------------
# Unknown system
# ---------------------------------------------------------------------------

class TestUnknownSystem:
    def test_unknown_system_raises(self):
        with pytest.raises(ValueError, match="Unknown ring-size system"):
            ring_size_to_diameter("cn", 10)


# ---------------------------------------------------------------------------
# Inverse: ring_diameter_to_size
# ---------------------------------------------------------------------------

class TestInverse:
    def test_us_round_trip_us7(self):
        d = ring_size_to_diameter("us", 7)
        back = ring_diameter_to_size("us", d)
        assert back == 7.0

    def test_us_round_trip_us7_5(self):
        d = ring_size_to_diameter("us", 7.5)
        back = ring_diameter_to_size("us", d)
        assert back == 7.5

    def test_us_round_trip_us0(self):
        d = ring_size_to_diameter("us", 0)
        back = ring_diameter_to_size("us", d)
        assert back == 0.0

    def test_uk_round_trip_n(self):
        d = ring_size_to_diameter("uk", "N")
        back = ring_diameter_to_size("uk", d)
        assert back == "N"

    def test_uk_round_trip_z(self):
        d = ring_size_to_diameter("uk", "Z")
        back = ring_diameter_to_size("uk", d)
        assert back == "Z"

    def test_eu_round_trip(self):
        d = ring_size_to_diameter("eu", 54)
        back = ring_diameter_to_size("eu", d)
        # Should round-trip back to 54.0 (nearest 0.5)
        assert abs(back - 54.0) < 0.5

    def test_jp_round_trip(self):
        d = ring_size_to_diameter("jp", 13)
        back = ring_diameter_to_size("jp", d)
        assert back == 13

    def test_inverse_zero_diameter_raises(self):
        with pytest.raises(ValueError, match="positive"):
            ring_diameter_to_size("us", 0)

    def test_inverse_negative_diameter_raises(self):
        with pytest.raises(ValueError, match="positive"):
            ring_diameter_to_size("us", -5.0)

    def test_inverse_unknown_system_raises(self):
        with pytest.raises(ValueError, match="Unknown ring-size system"):
            ring_diameter_to_size("xx", 17.0)


# ---------------------------------------------------------------------------
# compute_shank_params
# ---------------------------------------------------------------------------

class TestComputeShankParams:
    def test_basic_us7(self):
        p = compute_shank_params(7, "us", band_width=4.0, thickness=1.8,
                                  profile="comfort_fit", shoulder_style="plain")
        assert abs(p["inner_diameter_mm"] - 17.32) < 0.01
        assert abs(p["outer_diameter_mm"] - (17.32 + 2 * 1.8)) < 0.01
        assert p["profile"] == "comfort_fit"
        assert p["shoulder_style"] == "plain"

    def test_all_profiles_accepted(self):
        for pr in _VALID_PROFILES:
            p = compute_shank_params(7, "us", profile=pr, shoulder_style="plain")
            assert p["profile"] == pr

    def test_all_shoulder_styles_accepted(self):
        for ss in _VALID_SHOULDER_STYLES:
            p = compute_shank_params(7, "us", profile="flat", shoulder_style=ss)
            assert p["shoulder_style"] == ss

    def test_cathedral_shoulder_hints(self):
        p = compute_shank_params(7, "us", shoulder_style="cathedral")
        h = p["shoulder_hints"]
        assert h["type"] == "cathedral"
        assert h["arch_height_mm"] > 0
        assert h["arch_start_deg"] == 70.0

    def test_split_shank_hints(self):
        p = compute_shank_params(7, "us", shoulder_style="split_shank")
        h = p["shoulder_hints"]
        assert h["type"] == "split_shank"
        assert h["prong_gap_mm"] > 0

    def test_bypass_hints(self):
        p = compute_shank_params(7, "us", shoulder_style="bypass")
        h = p["shoulder_hints"]
        assert h["type"] == "bypass"
        assert h["bypass_offset_mm"] > 0

    def test_tapered_ratio_stored(self):
        p = compute_shank_params(7, "us", profile="tapered", taper_ratio=0.7)
        assert p["taper_ratio"] == 0.7

    def test_invalid_profile_raises(self):
        with pytest.raises(ValueError, match="Unknown profile"):
            compute_shank_params(7, "us", profile="round")

    def test_invalid_shoulder_style_raises(self):
        with pytest.raises(ValueError, match="Unknown shoulder_style"):
            compute_shank_params(7, "us", shoulder_style="prong")

    def test_zero_band_width_raises(self):
        with pytest.raises(ValueError, match="band_width"):
            compute_shank_params(7, "us", band_width=0)

    def test_zero_thickness_raises(self):
        with pytest.raises(ValueError, match="thickness"):
            compute_shank_params(7, "us", thickness=0)

    def test_negative_taper_ratio_raises(self):
        with pytest.raises(ValueError, match="taper_ratio"):
            compute_shank_params(7, "us", taper_ratio=-0.5)

    def test_circumference_formula(self):
        p = compute_shank_params(7, "us")
        # Values are rounded to 4 decimal places in the output; allow rounding error
        assert abs(p["circumference_mm"] - _PI * p["inner_diameter_mm"]) < 1e-3

    def test_uk_size_accepted(self):
        p = compute_shank_params("N", "uk")
        assert p["inner_diameter_mm"] > 0

    def test_size_system_stored(self):
        p = compute_shank_params(7, "us")
        assert p["size_system"] == "us"
        assert p["ring_size"] == 7


# ---------------------------------------------------------------------------
# ToolSpec declarations
# ---------------------------------------------------------------------------

class TestToolSpecs:
    def test_ring_size_spec_name(self):
        assert jewelry_ring_size_to_diameter_spec.name == "jewelry_ring_size_to_diameter"

    def test_ring_size_spec_system_enum(self):
        props = jewelry_ring_size_to_diameter_spec.input_schema["properties"]
        assert "system" in props
        assert set(props["system"]["enum"]) == _VALID_SYSTEMS

    def test_create_shank_spec_name(self):
        assert jewelry_create_ring_shank_spec.name == "jewelry_create_ring_shank"

    def test_create_shank_spec_profile_enum(self):
        props = jewelry_create_ring_shank_spec.input_schema["properties"]
        assert "profile" in props
        assert set(props["profile"]["enum"]) == _VALID_PROFILES

    def test_create_shank_spec_shoulder_enum(self):
        props = jewelry_create_ring_shank_spec.input_schema["properties"]
        assert "shoulder_style" in props
        assert set(props["shoulder_style"]["enum"]) == _VALID_SHOULDER_STYLES

    def test_create_shank_required_fields(self):
        req = set(jewelry_create_ring_shank_spec.input_schema["required"])
        assert "file_id" in req
        assert "ring_size" in req


# ---------------------------------------------------------------------------
# LLM tool runner: jewelry_ring_size_to_diameter
# ---------------------------------------------------------------------------

class TestRingSizeToDiameterTool:
    def _run(self, **kwargs):
        ctx, _, _ = make_ctx()
        return run_tool_sync(
            run_jewelry_ring_size_to_diameter(ctx, json.dumps(kwargs).encode())
        )

    def test_forward_us7(self):
        r = self._run(system="us", size=7)
        assert "error" not in r, f"Unexpected error: {r}"
        assert abs(r["inner_diameter_mm"] - 17.3196) < 0.01

    def test_forward_uk_n(self):
        r = self._run(system="uk", size="N")
        assert "error" not in r
        assert r["inner_diameter_mm"] > 0

    def test_inverse_diameter_us(self):
        r = self._run(system="us", diameter_mm=17.3196)
        assert "error" not in r
        assert "nearest_size" in r

    def test_missing_system(self):
        r = self._run(size=7)
        # system defaults to empty string — should fail validation
        assert "error" in r

    def test_invalid_system(self):
        r = self._run(system="cn", size=7)
        assert "error" in r

    def test_us_out_of_range(self):
        r = self._run(system="us", size=17)
        assert "error" in r

    def test_jp_out_of_range(self):
        r = self._run(system="jp", size=31)
        assert "error" in r


# ---------------------------------------------------------------------------
# LLM tool runner: jewelry_create_ring_shank
# ---------------------------------------------------------------------------

class TestCreateRingShankTool:
    def _run(self, ctx, file_id, **kwargs):
        args = {"file_id": str(file_id), **kwargs}
        return run_tool_sync(
            run_jewelry_create_ring_shank(ctx, json.dumps(args).encode())
        )

    def test_basic_us7_plain(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, system="us")
        assert "error" not in r, f"Unexpected error: {r}"
        assert r.get("op") == "ring_shank"
        # Node should be persisted
        doc = json.loads(store["content"])
        features = doc["features"]
        assert len(features) == 1
        assert features[0]["op"] == "ring_shank"

    def test_node_id_generated(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7)
        assert "error" not in r
        assert r.get("id", "").startswith("ring_shank-")

    def test_explicit_node_id(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, id="myring-1")
        assert "error" not in r
        assert r.get("id") == "myring-1"

    def test_second_node_increments_id(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7)
        r2 = self._run(ctx, fid, ring_size=8)
        assert "error" not in r2
        assert r2.get("id") == "ring_shank-2"

    def test_cathedral_shoulder(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, shoulder_style="cathedral")
        assert "error" not in r
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["shoulder_style"] == "cathedral"
        h = node["shoulder_hints"]
        assert h["type"] == "cathedral"
        assert h["arch_height_mm"] > 0

    def test_all_profiles_accepted(self):
        for pr in _VALID_PROFILES:
            ctx, store, fid = make_ctx()
            r = self._run(ctx, fid, ring_size=7, profile=pr)
            assert "error" not in r, f"Profile {pr!r} raised error: {r}"

    def test_all_shoulder_styles_accepted(self):
        for ss in _VALID_SHOULDER_STYLES:
            ctx, store, fid = make_ctx()
            r = self._run(ctx, fid, ring_size=7, shoulder_style=ss)
            assert "error" not in r, f"Shoulder {ss!r} raised error: {r}"

    def test_invalid_profile_bad_args(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, profile="round")
        assert "error" in r

    def test_invalid_shoulder_bad_args(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, shoulder_style="prong")
        assert "error" in r

    def test_invalid_system_bad_args(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, system="cn")
        assert "error" in r

    def test_zero_band_width_bad_args(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, band_width=0)
        assert "error" in r

    def test_zero_thickness_bad_args(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, thickness=0)
        assert "error" in r

    def test_missing_file_id_bad_args(self):
        ctx, store, fid = make_ctx()
        r = run_tool_sync(
            run_jewelry_create_ring_shank(ctx, json.dumps({"ring_size": 7}).encode())
        )
        assert "error" in r

    def test_missing_ring_size_bad_args(self):
        ctx, store, fid = make_ctx()
        r = run_tool_sync(
            run_jewelry_create_ring_shank(
                ctx, json.dumps({"file_id": str(fid)}).encode()
            )
        )
        assert "error" in r

    def test_invalid_file_id_bad_args(self):
        ctx, store, fid = make_ctx()
        r = run_tool_sync(
            run_jewelry_create_ring_shank(
                ctx, json.dumps({"file_id": "not-a-uuid", "ring_size": 7}).encode()
            )
        )
        assert "error" in r

    def test_non_feature_file_not_found(self):
        ctx, store, fid = make_ctx()
        store["kind"] = "sketch"
        r = self._run(ctx, fid, ring_size=7)
        assert "error" in r

    def test_node_contains_geometry(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, band_width=5.0, thickness=2.0)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["band_width_mm"] == 5.0
        assert node["thickness_mm"] == 2.0
        assert abs(node["inner_diameter_mm"] - 17.32) < 0.01

    def test_uk_ring_size(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size="N", system="uk")
        assert "error" not in r

    def test_eu_ring_size(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=54, system="eu")
        assert "error" not in r

    def test_jp_ring_size(self):
        ctx, store, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=13, system="jp")
        assert "error" not in r

    def test_tapered_profile_ratio_stored(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, profile="tapered", taper_ratio=0.6)
        doc = json.loads(store["content"])
        assert doc["features"][0]["taper_ratio"] == 0.6

    def test_invalid_json_bad_args(self):
        ctx, _, _ = make_ctx()
        r = run_tool_sync(
            run_jewelry_create_ring_shank(ctx, b"not json!")
        )
        assert "error" in r


# ---------------------------------------------------------------------------
# v2 profiles: compute_shank_params
# ---------------------------------------------------------------------------

# Complete set for quick loop tests
_V2_PROFILES = ["cigar_band", "bombe", "concave", "square", "hammered", "split_band"]


class TestV2Profiles:
    """Each new profile must produce a valid spec with correct profile_hints."""

    def test_all_v2_profiles_in_valid_set(self):
        for p in _V2_PROFILES:
            assert p in _VALID_PROFILES, f"{p!r} not in _VALID_PROFILES"

    def test_all_v2_profiles_accepted_by_compute(self):
        for p in _V2_PROFILES:
            r = compute_shank_params(7, "us", profile=p)
            assert r["profile"] == p, f"Profile {p!r} not stored correctly"

    def test_v2_profiles_emit_profile_hints(self):
        for p in _V2_PROFILES:
            r = compute_shank_params(7, "us", profile=p)
            assert "profile_hints" in r, f"{p!r} missing profile_hints"
            assert r["profile_hints"]["type"] == p

    # --- cigar_band ---

    def test_cigar_band_bevel_and_flat(self):
        r = compute_shank_params(7, "us", profile="cigar_band", band_width=6.0)
        h = r["profile_hints"]
        assert h["bevel_width_mm"] > 0
        assert h["flat_top_width_mm"] > 0
        # flat_top + 2 * bevel ≈ band_width
        total = h["flat_top_width_mm"] + 2 * h["bevel_width_mm"]
        assert abs(total - 6.0) < 0.01

    def test_cigar_band_custom_bevel_ratio(self):
        r = compute_shank_params(7, "us", profile="cigar_band", band_width=4.0,
                                  cigar_bevel_ratio=0.3)
        h = r["profile_hints"]
        assert abs(h["bevel_width_mm"] - 4.0 * 0.3) < 0.01

    def test_cigar_band_invalid_bevel_ratio(self):
        with pytest.raises(ValueError, match="cigar_bevel_ratio"):
            compute_shank_params(7, "us", profile="cigar_band", cigar_bevel_ratio=0.5)

    def test_cigar_band_zero_bevel_ratio_raises(self):
        with pytest.raises(ValueError, match="cigar_bevel_ratio"):
            compute_shank_params(7, "us", profile="cigar_band", cigar_bevel_ratio=0.0)

    # --- bombe ---

    def test_bombe_dome_height_positive(self):
        r = compute_shank_params(7, "us", profile="bombe", band_width=5.0)
        h = r["profile_hints"]
        assert h["dome_height_mm"] > 0
        assert h["dome_ratio"] == 0.5

    def test_bombe_custom_dome_ratio(self):
        r = compute_shank_params(7, "us", profile="bombe", band_width=4.0,
                                  bombe_dome_ratio=0.8)
        h = r["profile_hints"]
        assert abs(h["dome_ratio"] - 0.8) < 1e-9

    def test_bombe_zero_dome_ratio_raises(self):
        with pytest.raises(ValueError, match="bombe_dome_ratio"):
            compute_shank_params(7, "us", profile="bombe", bombe_dome_ratio=0.0)

    def test_bombe_over_one_dome_ratio_raises(self):
        with pytest.raises(ValueError, match="bombe_dome_ratio"):
            compute_shank_params(7, "us", profile="bombe", bombe_dome_ratio=1.5)

    # --- concave ---

    def test_concave_channel_dims(self):
        r = compute_shank_params(7, "us", profile="concave",
                                  band_width=5.0, thickness=2.0)
        h = r["profile_hints"]
        assert h["channel_depth_mm"] > 0
        assert h["channel_width_mm"] > 0

    def test_concave_depth_ratio_boundary_raises(self):
        with pytest.raises(ValueError, match="concave_depth_ratio"):
            compute_shank_params(7, "us", profile="concave", concave_depth_ratio=0.5)

    def test_concave_zero_depth_ratio_raises(self):
        with pytest.raises(ValueError, match="concave_depth_ratio"):
            compute_shank_params(7, "us", profile="concave", concave_depth_ratio=0.0)

    # --- square ---

    def test_square_hints_corner_radius_zero(self):
        r = compute_shank_params(7, "us", profile="square")
        h = r["profile_hints"]
        assert h["type"] == "square"
        assert h["corner_radius_mm"] == 0.0

    # --- hammered ---

    def test_hammered_default_32_facets(self):
        r = compute_shank_params(7, "us", profile="hammered")
        h = r["profile_hints"]
        assert h["facet_count"] == 32
        assert abs(h["facet_arc_deg"] - 360.0 / 32) < 0.001

    def test_hammered_custom_facet_count(self):
        r = compute_shank_params(7, "us", profile="hammered",
                                  hammered_facet_count=16)
        assert r["profile_hints"]["facet_count"] == 16

    def test_hammered_facet_count_too_low_raises(self):
        with pytest.raises(ValueError, match="hammered_facet_count"):
            compute_shank_params(7, "us", profile="hammered",
                                  hammered_facet_count=3)

    def test_hammered_facet_count_too_high_raises(self):
        with pytest.raises(ValueError, match="hammered_facet_count"):
            compute_shank_params(7, "us", profile="hammered",
                                  hammered_facet_count=200)

    def test_hammered_facet_arc_deg_formula(self):
        r = compute_shank_params(7, "us", profile="hammered",
                                  hammered_facet_count=12)
        assert abs(r["profile_hints"]["facet_arc_deg"] - 30.0) < 0.001

    # --- split_band ---

    def test_split_band_default_gap(self):
        r = compute_shank_params(7, "us", profile="split_band", band_width=4.0)
        h = r["profile_hints"]
        assert h["type"] == "split_band"
        assert h["gap_mm"] == 1.0
        # each rail = (4.0 - 1.0) / 2 = 1.5
        assert abs(h["rail_width_mm"] - 1.5) < 0.01

    def test_split_band_custom_gap(self):
        r = compute_shank_params(7, "us", profile="split_band",
                                  band_width=5.0, split_band_gap_mm=1.5)
        h = r["profile_hints"]
        assert abs(h["gap_mm"] - 1.5) < 1e-9
        assert abs(h["rail_width_mm"] - (5.0 - 1.5) / 2) < 0.01

    def test_split_band_zero_gap_raises(self):
        with pytest.raises(ValueError, match="split_band_gap_mm"):
            compute_shank_params(7, "us", profile="split_band",
                                  split_band_gap_mm=0.0)

    def test_split_band_gap_too_large_raises(self):
        # gap = band_width − 0.5 − epsilon leaves no room for rails
        with pytest.raises(ValueError, match="split_band_gap_mm"):
            compute_shank_params(7, "us", profile="split_band",
                                  band_width=4.0, split_band_gap_mm=3.6)

    def test_original_profiles_no_profile_hints(self):
        """Original profiles must NOT have profile_hints key."""
        for p in ["d_shape", "comfort_fit", "flat", "half_round",
                   "knife_edge", "euro", "tapered"]:
            r = compute_shank_params(7, "us", profile=p)
            assert "profile_hints" not in r, (
                f"Original profile {p!r} should not emit profile_hints"
            )


# ---------------------------------------------------------------------------
# v2 profiles: LLM tool round-trip
# ---------------------------------------------------------------------------

class TestV2ProfilesTool:
    def _run(self, ctx, fid, **kwargs):
        args = {"file_id": str(fid), **kwargs}
        return run_tool_sync(
            run_jewelry_create_ring_shank(ctx, json.dumps(args).encode())
        )

    def test_all_v2_profiles_accepted_by_tool(self):
        for p in _V2_PROFILES:
            ctx, store, fid = make_ctx()
            r = self._run(ctx, fid, ring_size=7, profile=p)
            assert "error" not in r, f"Tool rejected profile {p!r}: {r}"
            assert r["profile"] == p

    def test_hammered_facet_count_via_tool(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, profile="hammered",
                  hammered_facet_count=16)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["profile_hints"]["facet_count"] == 16

    def test_split_band_gap_via_tool(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, profile="split_band",
                  band_width=5.0, split_band_gap_mm=1.2)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert abs(node["profile_hints"]["gap_mm"] - 1.2) < 1e-9

    def test_bombe_dome_ratio_via_tool(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, profile="bombe", bombe_dome_ratio=0.7)
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert abs(node["profile_hints"]["dome_ratio"] - 0.7) < 1e-9

    def test_tool_spec_profile_enum_includes_v2(self):
        props = jewelry_create_ring_shank_spec.input_schema["properties"]
        enum_set = set(props["profile"]["enum"])
        for p in _V2_PROFILES:
            assert p in enum_set, f"{p!r} missing from tool spec enum"

    def test_invalid_v2_param_bad_args(self):
        """hammered_facet_count=3 is out of range → BAD_ARGS from tool."""
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, profile="hammered",
                      hammered_facet_count=3)
        assert "error" in r

    def test_split_band_gap_zero_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, profile="split_band",
                      band_width=4.0, split_band_gap_mm=0.0)
        assert "error" in r


# ---------------------------------------------------------------------------
# EngravingSpec
# ---------------------------------------------------------------------------

class TestEngravingSpec:
    def test_defaults(self):
        e = EngravingSpec(text="Hello")
        d = e.to_dict()
        assert d["text"] == "Hello"
        assert d["font_height_mm"] == 1.5
        assert d["depth_mm"] == 0.3
        assert d["position_deg"] == 180.0
        assert d["align"] == "centre"

    def test_custom_values(self):
        e = EngravingSpec(
            text="Always",
            font_height_mm=2.0,
            depth_mm=0.5,
            position_deg=90.0,
            align="left",
        )
        d = e.to_dict()
        assert d["font_height_mm"] == 2.0
        assert d["align"] == "left"

    def test_empty_text_raises(self):
        e = EngravingSpec(text="")
        with pytest.raises(ValueError, match="non-empty"):
            e.validate()

    def test_whitespace_text_raises(self):
        e = EngravingSpec(text="   ")
        with pytest.raises(ValueError, match="non-empty"):
            e.validate()

    def test_text_too_long_raises(self):
        e = EngravingSpec(text="x" * 201)
        with pytest.raises(ValueError, match="200"):
            e.validate()

    def test_zero_font_height_raises(self):
        e = EngravingSpec(text="Hi", font_height_mm=0.0)
        with pytest.raises(ValueError, match="font_height_mm"):
            e.validate()

    def test_negative_font_height_raises(self):
        e = EngravingSpec(text="Hi", font_height_mm=-1.0)
        with pytest.raises(ValueError, match="font_height_mm"):
            e.validate()

    def test_zero_depth_raises(self):
        e = EngravingSpec(text="Hi", depth_mm=0.0)
        with pytest.raises(ValueError, match="depth_mm"):
            e.validate()

    def test_position_out_of_range_raises(self):
        e = EngravingSpec(text="Hi", position_deg=400.0)
        with pytest.raises(ValueError, match="position_deg"):
            e.validate()

    def test_position_negative_raises(self):
        e = EngravingSpec(text="Hi", position_deg=-10.0)
        with pytest.raises(ValueError, match="position_deg"):
            e.validate()

    def test_invalid_align_raises(self):
        e = EngravingSpec(text="Hi", align="justify")
        with pytest.raises(ValueError, match="align"):
            e.validate()

    def test_engraving_in_shank_params(self):
        e = EngravingSpec(text="Love")
        r = compute_shank_params(7, "us", engraving=e)
        assert "engraving" in r
        assert r["engraving"]["text"] == "Love"

    def test_no_engraving_no_key(self):
        r = compute_shank_params(7, "us")
        assert "engraving" not in r


# ---------------------------------------------------------------------------
# Engraving via LLM tool
# ---------------------------------------------------------------------------

class TestEngravingTool:
    def _run(self, ctx, fid, **kwargs):
        args = {"file_id": str(fid), **kwargs}
        return run_tool_sync(
            run_jewelry_create_ring_shank(ctx, json.dumps(args).encode())
        )

    def test_engraving_stored_in_node(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7,
                  engraving={"text": "Forever", "font_height_mm": 2.0, "depth_mm": 0.4})
        doc = json.loads(store["content"])
        eng = doc["features"][0]["engraving"]
        assert eng["text"] == "Forever"
        assert eng["font_height_mm"] == 2.0
        assert eng["depth_mm"] == 0.4

    def test_engraving_default_position(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, engraving={"text": "Hi"})
        doc = json.loads(store["content"])
        eng = doc["features"][0]["engraving"]
        assert eng["position_deg"] == 180.0
        assert eng["align"] == "centre"

    def test_engraving_missing_text_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7,
                      engraving={"font_height_mm": 1.5})
        assert "error" in r

    def test_engraving_not_an_object_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, engraving="not a dict")
        assert "error" in r

    def test_engraving_zero_depth_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7,
                      engraving={"text": "Hi", "depth_mm": 0.0})
        assert "error" in r

    def test_engraving_invalid_align_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7,
                      engraving={"text": "Hi", "align": "center"})
        assert "error" in r


# ---------------------------------------------------------------------------
# SizingBeadSpec
# ---------------------------------------------------------------------------

class TestSizingBeadSpec:
    def test_defaults(self):
        sb = SizingBeadSpec()
        d = sb.to_dict()
        assert d["count"] == 2
        assert d["bead_diameter_mm"] == 1.0
        assert d["bead_height_mm"] == 0.4
        assert d["position_deg"] == 270.0

    def test_custom_values(self):
        sb = SizingBeadSpec(count=4, bead_diameter_mm=1.2, bead_height_mm=0.35,
                             position_deg=90.0)
        d = sb.to_dict()
        assert d["count"] == 4
        assert d["bead_diameter_mm"] == 1.2

    def test_count_zero_raises(self):
        sb = SizingBeadSpec(count=0)
        with pytest.raises(ValueError, match="count"):
            sb.validate()

    def test_count_too_high_raises(self):
        sb = SizingBeadSpec(count=5)
        with pytest.raises(ValueError, match="count"):
            sb.validate()

    def test_zero_bead_diameter_raises(self):
        sb = SizingBeadSpec(bead_diameter_mm=0.0)
        with pytest.raises(ValueError, match="bead_diameter_mm"):
            sb.validate()

    def test_zero_bead_height_raises(self):
        sb = SizingBeadSpec(bead_height_mm=0.0)
        with pytest.raises(ValueError, match="bead_height_mm"):
            sb.validate()

    def test_position_out_of_range_raises(self):
        sb = SizingBeadSpec(position_deg=400.0)
        with pytest.raises(ValueError, match="position_deg"):
            sb.validate()

    def test_height_exceeds_thickness_quarter_raises(self):
        """bead_height ≥ thickness/4 should raise."""
        sb = SizingBeadSpec(bead_height_mm=1.0)
        with pytest.raises(ValueError, match="perforation"):
            sb.validate(band_thickness_mm=3.0)  # threshold = 0.75

    def test_height_just_under_threshold_ok(self):
        sb = SizingBeadSpec(bead_height_mm=0.74)
        sb.validate(band_thickness_mm=3.0)  # 3.0/4 = 0.75 — just under OK

    def test_sizing_beads_in_shank_params(self):
        sb = SizingBeadSpec(count=2, bead_diameter_mm=1.0, bead_height_mm=0.3)
        r = compute_shank_params(7, "us", thickness=2.0, sizing_beads=sb)
        assert "sizing_beads" in r
        assert r["sizing_beads"]["count"] == 2

    def test_no_sizing_beads_no_key(self):
        r = compute_shank_params(7, "us")
        assert "sizing_beads" not in r


# ---------------------------------------------------------------------------
# Sizing beads via LLM tool
# ---------------------------------------------------------------------------

class TestSizingBeadsTool:
    def _run(self, ctx, fid, **kwargs):
        args = {"file_id": str(fid), **kwargs}
        return run_tool_sync(
            run_jewelry_create_ring_shank(ctx, json.dumps(args).encode())
        )

    def test_sizing_beads_stored(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, thickness=2.0,
                  sizing_beads={"count": 2, "bead_diameter_mm": 1.0, "bead_height_mm": 0.3})
        doc = json.loads(store["content"])
        sb = doc["features"][0]["sizing_beads"]
        assert sb["count"] == 2
        assert sb["bead_diameter_mm"] == 1.0

    def test_sizing_beads_invalid_count_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, thickness=2.0,
                      sizing_beads={"count": 5})
        assert "error" in r

    def test_sizing_beads_not_object_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, sizing_beads="two beads")
        assert "error" in r

    def test_sizing_beads_perforation_bad_args(self):
        """bead_height ≥ thickness/4 must error."""
        ctx, _, fid = make_ctx()
        # thickness=2.0 → limit = 0.5 mm; bead_height=1.0 exceeds it
        r = self._run(ctx, fid, ring_size=7, thickness=2.0,
                      sizing_beads={"count": 2, "bead_height_mm": 1.0})
        assert "error" in r


# ---------------------------------------------------------------------------
# Sizing/fit features: comfort_fit_radius, finger_fit_taper, width_profile
# ---------------------------------------------------------------------------

class TestSizingFitFeatures:
    # --- comfort_fit_radius ---

    def test_comfort_fit_radius_stored(self):
        r = compute_shank_params(7, "us", comfort_fit_radius=4.5)
        assert "comfort_fit_radius_mm" in r
        assert r["comfort_fit_radius_mm"] == 4.5

    def test_comfort_fit_radius_not_set_no_key(self):
        r = compute_shank_params(7, "us")
        assert "comfort_fit_radius_mm" not in r

    def test_comfort_fit_radius_zero_raises(self):
        with pytest.raises(ValueError, match="comfort_fit_radius"):
            compute_shank_params(7, "us", comfort_fit_radius=0.0)

    def test_comfort_fit_radius_negative_raises(self):
        with pytest.raises(ValueError, match="comfort_fit_radius"):
            compute_shank_params(7, "us", comfort_fit_radius=-1.0)

    # --- finger_fit_taper ---

    def test_finger_fit_taper_stored(self):
        r = compute_shank_params(7, "us", finger_fit_taper=5.0)
        assert "finger_fit_taper_deg" in r
        assert r["finger_fit_taper_deg"] == 5.0

    def test_finger_fit_taper_zero_not_stored(self):
        """Zero taper (default) should not add the key."""
        r = compute_shank_params(7, "us", finger_fit_taper=0.0)
        assert "finger_fit_taper_deg" not in r

    def test_finger_fit_taper_at_limit(self):
        r = compute_shank_params(7, "us", finger_fit_taper=15.0)
        assert r["finger_fit_taper_deg"] == 15.0

    def test_finger_fit_taper_over_limit_raises(self):
        with pytest.raises(ValueError, match="finger_fit_taper"):
            compute_shank_params(7, "us", finger_fit_taper=16.0)

    def test_finger_fit_taper_negative_raises(self):
        with pytest.raises(ValueError, match="finger_fit_taper"):
            compute_shank_params(7, "us", finger_fit_taper=-1.0)

    # --- width_profile ---

    def test_width_profile_stored(self):
        r = compute_shank_params(7, "us", width_profile=[1.0, 0.85, 0.7])
        assert "width_profile" in r
        assert r["width_profile"] == [1.0, 0.85, 0.7]

    def test_width_profile_not_set_no_key(self):
        r = compute_shank_params(7, "us")
        assert "width_profile" not in r

    def test_width_profile_two_points_min(self):
        r = compute_shank_params(7, "us", width_profile=[1.0, 0.6])
        assert len(r["width_profile"]) == 2

    def test_width_profile_ten_points_max(self):
        curve = [1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55]
        r = compute_shank_params(7, "us", width_profile=curve)
        assert len(r["width_profile"]) == 10

    def test_width_profile_too_few_raises(self):
        with pytest.raises(ValueError, match="2–10"):
            compute_shank_params(7, "us", width_profile=[1.0])

    def test_width_profile_too_many_raises(self):
        with pytest.raises(ValueError, match="2–10"):
            compute_shank_params(7, "us", width_profile=[1.0] * 11)

    def test_width_profile_value_zero_raises(self):
        with pytest.raises(ValueError, match=r"\(0, 1\]"):
            compute_shank_params(7, "us", width_profile=[0.0, 0.8])

    def test_width_profile_value_over_one_raises(self):
        with pytest.raises(ValueError, match=r"\(0, 1\]"):
            compute_shank_params(7, "us", width_profile=[1.0, 1.1])

    def test_width_profile_non_numeric_raises(self):
        with pytest.raises(ValueError, match="must be a number"):
            compute_shank_params(7, "us", width_profile=[1.0, "x"])

    def test_width_profile_not_a_list_raises(self):
        with pytest.raises(ValueError, match="2–10"):
            compute_shank_params(7, "us", width_profile="not-a-list")


# ---------------------------------------------------------------------------
# _validate_width_profile (unit tests on the helper)
# ---------------------------------------------------------------------------

class TestValidateWidthProfile:
    def test_valid_curve(self):
        result = _validate_width_profile([1.0, 0.8, 0.6])
        assert result == [1.0, 0.8, 0.6]

    def test_coerces_to_float(self):
        result = _validate_width_profile([1, 1])  # ints
        assert all(isinstance(v, float) for v in result)

    def test_at_max_boundary_passes(self):
        _validate_width_profile([1.0, 1.0])  # exactly 1.0 is valid

    def test_over_max_raises(self):
        with pytest.raises(ValueError):
            _validate_width_profile([1.0, 1.001])

    def test_at_min_boundary_raises(self):
        with pytest.raises(ValueError):
            _validate_width_profile([0.0, 1.0])  # 0.0 not valid (must be > 0)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            _validate_width_profile([])

    def test_single_item_raises(self):
        with pytest.raises(ValueError):
            _validate_width_profile([1.0])


# ---------------------------------------------------------------------------
# Sizing/fit features via LLM tool
# ---------------------------------------------------------------------------

class TestSizingFitTool:
    def _run(self, ctx, fid, **kwargs):
        args = {"file_id": str(fid), **kwargs}
        return run_tool_sync(
            run_jewelry_create_ring_shank(ctx, json.dumps(args).encode())
        )

    def test_comfort_fit_radius_stored(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, comfort_fit_radius=4.5)
        doc = json.loads(store["content"])
        assert doc["features"][0]["comfort_fit_radius_mm"] == 4.5

    def test_comfort_fit_radius_zero_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, comfort_fit_radius=0.0)
        assert "error" in r

    def test_finger_fit_taper_stored(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, finger_fit_taper=7.5)
        doc = json.loads(store["content"])
        assert doc["features"][0]["finger_fit_taper_deg"] == 7.5

    def test_finger_fit_taper_over_limit_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, finger_fit_taper=20.0)
        assert "error" in r

    def test_width_profile_stored(self):
        ctx, store, fid = make_ctx()
        self._run(ctx, fid, ring_size=7, width_profile=[1.0, 0.8, 0.6])
        doc = json.loads(store["content"])
        assert doc["features"][0]["width_profile"] == [1.0, 0.8, 0.6]

    def test_width_profile_bad_values_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, width_profile=[0.0, 0.8])
        assert "error" in r

    def test_width_profile_too_few_bad_args(self):
        ctx, _, fid = make_ctx()
        r = self._run(ctx, fid, ring_size=7, width_profile=[1.0])
        assert "error" in r

    def test_all_v2_fit_features_combined(self):
        """Combined call with engraving + sizing_beads + width_profile."""
        ctx, store, fid = make_ctx()
        r = self._run(
            ctx, fid,
            ring_size=7, system="us",
            band_width=5.0, thickness=2.0,
            profile="hammered", hammered_facet_count=24,
            shoulder_style="cathedral",
            engraving={"text": "Forever", "depth_mm": 0.3},
            sizing_beads={"count": 2, "bead_height_mm": 0.3},
            comfort_fit_radius=4.0,
            finger_fit_taper=3.0,
            width_profile=[1.0, 0.9, 0.8],
        )
        assert "error" not in r, f"Combined call failed: {r}"
        doc = json.loads(store["content"])
        node = doc["features"][0]
        assert node["engraving"]["text"] == "Forever"
        assert node["sizing_beads"]["count"] == 2
        assert node["comfort_fit_radius_mm"] == 4.0
        assert node["finger_fit_taper_deg"] == 3.0
        assert node["width_profile"] == [1.0, 0.9, 0.8]
        assert node["profile_hints"]["facet_count"] == 24


# ---------------------------------------------------------------------------
# OCC-gated solid tests
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.occ_helpers import _OCC_AVAILABLE as _OCC
except ImportError:
    _OCC = False

pytestmark_occ = pytest.mark.skipif(
    not _OCC,
    reason="pythonOCC not installed; install with: conda install -c conda-forge pythonocc-core"
)


@pytestmark_occ
class TestRingShankOCC:
    """Structural smoke tests that require pythonOCC.

    These verify that the ring_shank node parameters are geometrically coherent
    when OCCT is present.  Full sweep evaluation lives in the occtWorker JS tests.
    """

    def test_inner_radius_positive(self):
        """Inner radius must be positive — sanity check for sweep origin."""
        d = ring_size_to_diameter("us", 7)
        r = d / 2.0
        assert r > 0, "Inner radius must be positive for a valid sweep circle."

    def test_outer_gt_inner(self):
        """Outer diameter must exceed inner diameter."""
        p = compute_shank_params(7, "us", thickness=1.8)
        assert p["outer_diameter_mm"] > p["inner_diameter_mm"]

    def test_shank_params_valid_for_sweep(self):
        """Verify shank params include all fields the occtWorker expects."""
        p = compute_shank_params(7, "us", band_width=4.0, thickness=1.8,
                                  profile="comfort_fit", shoulder_style="cathedral")
        required_keys = {
            "inner_diameter_mm",
            "outer_diameter_mm",
            "circumference_mm",
            "band_width_mm",
            "thickness_mm",
            "profile",
            "shoulder_style",
            "shoulder_hints",
        }
        missing = required_keys - set(p.keys())
        assert not missing, f"Missing keys in shank params: {missing}"
