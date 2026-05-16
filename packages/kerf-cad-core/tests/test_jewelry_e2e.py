"""
End-to-end integration test for the jewelry pipeline.

Drives a realistic jeweller workflow through the actual registered tools
(pure-Python only, no OCC, no network):

  1. Gemstone sizing   — carat → mm dimensions, proportion report
  2. Gem seat          — seat geometry derived from stone proportions
  3. Prong/bezel setting — setting nodes referencing stone diameter
  4. Ring shank        — size a shank for the correct ring finger size
  5. Pieces            — assemble a solitaire pendant and earring pair
  6. Metal weight      — compute weight and casting cost for the shank volume
  7. Full quote        — multi-stone quote with labour, setting, markup
  8. Casting export    — casting manifest for lost-wax production
  9. Templates         — list + instantiate a template recipe

Cross-tool consistency assertions (the point of this file):
  - seat bore (girdle_radius_mm × 2) ≈ gemstone girdle diameter + clearance
  - ring inner_diameter_mm matches the diameter computed from ring_size_to_diameter
  - metal cost scales proportionally with volume
  - gross_grams > net_grams for any non-zero casting allowance
  - carat round-trip: mm_from_carat(carat_from_mm(d)) == d
  - quote total == subtotal + markup; subtotal == metal + stone + labour
  - casting export pour weight ≥ net weight
  - METAL_DENSITY_G_CM3 table is consistent between metal_cost and casting_export

All tool runners (async) are invoked via asyncio.new_event_loop().run_until_complete().
All feature-file ops use an in-memory fake pool (no DB).
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

# ---------------------------------------------------------------------------
# Imports from jewelry sub-modules
# ---------------------------------------------------------------------------

from kerf_cad_core.jewelry.gemstones import (
    GEMSTONE_CUTS,
    GEMSTONE_DENSITIES,
    carat_from_mm,
    mm_from_carat,
    gemstone_proportions,
    run_jewelry_create_gemstone,
    run_jewelry_gem_report,
    run_jewelry_gem_catalog,
)
from kerf_cad_core.jewelry.gem_seat import (
    seat_geometry,
    channel_seat_geometry,
    bezel_seat_geometry,
    gypsy_seat_geometry,
    pave_field_seat_geometry,
)
from kerf_cad_core.jewelry.settings import (
    build_prong_head_node,
    build_bezel_node,
    build_channel_node,
    build_pave_array_node,
    run_jewelry_create_prong_head,
    run_jewelry_create_bezel,
)
from kerf_cad_core.jewelry.ring import (
    ring_size_to_diameter,
    ring_diameter_to_size,
    compute_shank_params,
    run_jewelry_create_ring_shank,
    run_jewelry_ring_size_to_diameter,
    _US_ID_INTERCEPT,
    _US_ID_SLOPE,
    _PI,
)
from kerf_cad_core.jewelry.metal_cost import (
    METAL_DENSITY_G_CM3,
    METAL_HALLMARK,
    METAL_PRICE_PRESETS,
    casting_cost,
    casting_weight,
    metal_weight,
    stone_cost_line_items,
    jewelry_quote,
    labour_cost,
    mm_to_carat,
)
from kerf_cad_core.jewelry.casting_export import (
    casting_export_summary,
    estimate_metal_grams,
    estimate_pour_grams,
    get_shrinkage_pct,
    apply_shrinkage_scale,
)
from kerf_cad_core.jewelry.templates import (
    list_templates,
    get_template,
    instantiate,
    run_list_jewelry_templates,
    run_instantiate_jewelry_template,
)
from kerf_cad_core.jewelry.pieces import (
    compute_pendant_params,
    compute_earring_params,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(initial_content: str = ""):
    """Return (ctx, store, file_id) with an in-memory fake pool."""
    store = {
        "content": initial_content or json.dumps({"version": 1, "features": []}),
        "kind": "feature",
    }
    project_id = uuid.uuid4()
    file_id = uuid.uuid4()

    class _FakePool:
        def fetchone(self, query, *args):
            if store["kind"] == "NOT_FOUND":
                return None
            return (store["content"], store["kind"])

        def execute(self, query, *args):
            if args:
                store["content"] = args[0]

    from kerf_core.utils.context import ProjectCtx
    ctx = ProjectCtx(
        pool=_FakePool(),
        storage=None,
        project_id=project_id,
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )
    return ctx, store, file_id


def _run(coro) -> dict:
    """Run an async coroutine and return the parsed JSON response."""
    raw = asyncio.new_event_loop().run_until_complete(coro)
    return json.loads(raw)


def _tool_ok(result: dict) -> bool:
    """Return True if the tool result is a success (no 'error' key)."""
    return "error" not in result and "code" not in result


# ---------------------------------------------------------------------------
# Workflow constants
# ---------------------------------------------------------------------------

STONE_CUT    = "round_brilliant"
STONE_CARAT  = 0.75          # 3/4 carat
RING_SIZE_US = 7             # typical women's US ring size
METAL_KEY    = "18k_yellow"  # 18k yellow gold
METAL_PPG    = 48.0          # approximate USD/g from preset


# ============================================================================
# 1. Gemstone sizing — pure-Python carat ↔ mm
# ============================================================================

class TestGemstoneSizing:
    """Step 1: resolve stone dimensions from carat weight."""

    def test_mm_from_carat_gives_positive_diameter(self):
        d = mm_from_carat(STONE_CUT, STONE_CARAT)
        assert d > 0

    def test_round_brilliant_075ct_in_typical_range(self):
        """0.75 ct round brilliant should be ~5.8–6.0 mm (industry tables)."""
        d = mm_from_carat(STONE_CUT, STONE_CARAT)
        assert 5.5 < d < 6.5, f"0.75 ct diameter {d:.3f} mm outside expected 5.5–6.5 mm"

    def test_carat_round_trip_all_common_cuts(self):
        """carat_from_mm(mm_from_carat(ct)) == ct for common cuts."""
        for cut in ["round_brilliant", "princess", "oval", "emerald", "cushion", "pear"]:
            for ct in [0.25, 0.50, 1.0, 2.0]:
                d = mm_from_carat(cut, ct)
                back = carat_from_mm(cut, d)
                assert back == pytest.approx(ct, rel=1e-9), (
                    f"{cut} @ {ct} ct: round-trip error, got {back}"
                )

    def test_carat_increases_monotonically_with_diameter(self):
        for cut in ["round_brilliant", "princess", "oval"]:
            c1 = carat_from_mm(cut, 4.0)
            c2 = carat_from_mm(cut, 6.0)
            c3 = carat_from_mm(cut, 8.0)
            assert c1 < c2 < c3, f"{cut}: carat not monotone with diameter"

    def test_coloured_stone_density_correction(self):
        """Ruby (3.99 g/cm³) is denser than diamond (3.51) → smaller mm per carat."""
        d_diamond = mm_from_carat(STONE_CUT, 1.0, material="diamond")
        d_ruby    = mm_from_carat(STONE_CUT, 1.0, material="ruby")
        assert d_ruby < d_diamond, "Ruby (denser) should have smaller diameter per carat"

    def test_gemstone_proportions_diameter_matches_mm_from_carat(self):
        """gemstone_proportions from carat should match mm_from_carat."""
        props = gemstone_proportions(STONE_CUT, carat=STONE_CARAT)
        expected_d = mm_from_carat(STONE_CUT, STONE_CARAT)
        assert props.diameter_mm == pytest.approx(expected_d, rel=1e-9)

    def test_gemstone_proportions_depth_sane(self):
        """Total depth of a round brilliant should be ~60–65% of diameter."""
        props = gemstone_proportions(STONE_CUT, carat=STONE_CARAT)
        assert 55.0 < props.total_depth_pct < 75.0, (
            f"total_depth_pct={props.total_depth_pct:.1f}% outside 55–75%"
        )

    def test_gem_catalog_runner_ok(self):
        ctx, _, _ = _make_ctx()
        result = _run(run_jewelry_gem_catalog(
            ctx, json.dumps({"query": "diamond"}).encode()
        ))
        assert _tool_ok(result)
        assert result["count"] >= 1


# ============================================================================
# 2. Gem seat geometry — bore vs stone girdle cross-tool check
# ============================================================================

class TestGemSeatGeometry:
    """Step 2: verify seat geometry is consistent with stone proportions."""

    def setup_method(self):
        self.props = gemstone_proportions(STONE_CUT, carat=STONE_CARAT)

    def test_seat_girdle_radius_exceeds_stone_radius(self):
        """Seat bore must be slightly larger than the stone girdle to allow setting."""
        geom = seat_geometry(
            cut=STONE_CUT,
            diameter_mm=self.props.diameter_mm,
            pavilion_angle_deg=self.props.pavilion_angle_deg,
            pavilion_depth_pct=self.props.pavilion_depth_pct,
            girdle_pct=self.props.girdle_pct,
            crown_angle_deg=self.props.crown_angle_deg,
        )
        stone_r = self.props.diameter_mm / 2.0
        seat_r  = geom["girdle_radius_mm"]
        assert seat_r > stone_r, "Seat radius must exceed stone radius"
        clearance = seat_r - stone_r
        assert clearance < 0.5, f"Seat clearance {clearance:.4f} mm seems too large"

    def test_seat_bore_radius_matches_formula(self):
        """girdle_radius_mm = round(diameter/2 + clearance, 4) — verify formula."""
        CLEARANCE = 0.05
        geom = seat_geometry(
            cut=STONE_CUT,
            diameter_mm=self.props.diameter_mm,
            pavilion_angle_deg=self.props.pavilion_angle_deg,
            pavilion_depth_pct=self.props.pavilion_depth_pct,
            girdle_pct=self.props.girdle_pct,
            crown_angle_deg=self.props.crown_angle_deg,
            girdle_clearance_mm=CLEARANCE,
        )
        expected = round(self.props.diameter_mm / 2.0 + CLEARANCE, 4)
        assert geom["girdle_radius_mm"] == pytest.approx(expected, abs=1e-4)

    def test_seat_total_depth_exceeds_pavilion_depth(self):
        """Total cutter depth must accommodate at least the pavilion depth."""
        geom = seat_geometry(
            cut=STONE_CUT,
            diameter_mm=self.props.diameter_mm,
            pavilion_angle_deg=self.props.pavilion_angle_deg,
            pavilion_depth_pct=self.props.pavilion_depth_pct,
            girdle_pct=self.props.girdle_pct,
            crown_angle_deg=self.props.crown_angle_deg,
        )
        pav_mm = self.props.diameter_mm * self.props.pavilion_depth_pct / 100.0
        assert geom["total_cutter_depth_mm"] > pav_mm

    def test_channel_seat_n_stones_matches(self):
        """channel_seat_geometry returns exactly N stone positions."""
        N = 5
        props = gemstone_proportions("baguette", diameter_mm=3.0)
        geom = channel_seat_geometry(
            cut="baguette",
            diameter_mm=3.0,
            n_stones=N,
            pitch_mm=3.3,
            pavilion_angle_deg=props.pavilion_angle_deg,
            pavilion_depth_pct=props.pavilion_depth_pct,
            girdle_pct=props.girdle_pct,
            crown_angle_deg=props.crown_angle_deg,
        )
        assert geom["n_stones"] == N
        assert len(geom["stone_positions"]) == N

    def test_channel_seat_groove_length_formula(self):
        """groove_length = (n-1)*pitch + 2*girdle_radius (includes end half-stones)."""
        N = 5
        PITCH = 3.3
        CLEARANCE = 0.05
        props = gemstone_proportions("baguette", diameter_mm=3.0)
        geom = channel_seat_geometry(
            cut="baguette",
            diameter_mm=3.0,
            n_stones=N,
            pitch_mm=PITCH,
            pavilion_angle_deg=props.pavilion_angle_deg,
            pavilion_depth_pct=props.pavilion_depth_pct,
            girdle_pct=props.girdle_pct,
            crown_angle_deg=props.crown_angle_deg,
            girdle_clearance_mm=CLEARANCE,
        )
        # groove_length = (n-1)*pitch + 2*girdle_radius (from channel_seat_geometry source)
        girdle_r = round(3.0 / 2.0 + CLEARANCE, 4)
        expected = (N - 1) * PITCH + 2 * girdle_r
        assert geom["groove_length_mm"] == pytest.approx(expected, abs=1e-3)

    def test_bezel_seat_inner_bore_matches_stone(self):
        """bezel_seat inner_bore_top_radius ≈ stone girdle radius + clearance."""
        d = self.props.diameter_mm
        DEFAULT_CLEARANCE = 0.05  # from bezel_seat_geometry default
        geom = bezel_seat_geometry(
            cut=STONE_CUT,
            diameter_mm=d,
            pavilion_angle_deg=self.props.pavilion_angle_deg,
            pavilion_depth_pct=self.props.pavilion_depth_pct,
            girdle_pct=self.props.girdle_pct,
            crown_angle_deg=self.props.crown_angle_deg,
        )
        # inner_bore_top_radius is the key exposed by bezel_seat_geometry
        assert "inner_bore_top_radius" in geom
        assert geom["inner_bore_top_radius"] > d / 2.0

    def test_pave_field_n_stones_positive(self):
        """pave_field_seat_geometry returns n_stones > 0 for a reasonable field."""
        geom = pave_field_seat_geometry(
            cut="round_brilliant",
            diameter_mm=1.5,
            field_width_mm=10.0,
            field_height_mm=6.0,
            pavilion_angle_deg=40.75,
            pavilion_depth_pct=43.1,
            girdle_pct=2.5,
            crown_angle_deg=34.5,
        )
        assert geom["n_stones"] > 0
        assert len(geom["stone_positions"]) == geom["n_stones"]

    def test_seat_larger_stone_has_deeper_cutter(self):
        """A larger stone's seat should have a deeper cutter (scales with diameter)."""
        props_small = gemstone_proportions(STONE_CUT, diameter_mm=4.0)
        props_large = gemstone_proportions(STONE_CUT, diameter_mm=8.0)

        def _seat(props):
            return seat_geometry(
                cut=STONE_CUT,
                diameter_mm=props.diameter_mm,
                pavilion_angle_deg=props.pavilion_angle_deg,
                pavilion_depth_pct=props.pavilion_depth_pct,
                girdle_pct=props.girdle_pct,
                crown_angle_deg=props.crown_angle_deg,
            )

        gs = _seat(props_small)
        gl = _seat(props_large)
        assert gl["total_cutter_depth_mm"] > gs["total_cutter_depth_mm"]
        assert gl["girdle_radius_mm"] > gs["girdle_radius_mm"]


# ============================================================================
# 3. Settings — prong head and bezel setting nodes
# ============================================================================

class TestSettings:
    """Step 3: setting nodes reference stone diameter correctly."""

    def setup_method(self):
        self.props = gemstone_proportions(STONE_CUT, carat=STONE_CARAT)
        self.stone_d = self.props.diameter_mm

    def test_prong_head_outer_diameter_larger_than_stone(self):
        node = build_prong_head_node(
            node_id="prong-001",
            stone_diameter=self.stone_d,
            prong_count=4,
            prong_wire_diameter=0.6,
            prong_height=1.5,
            head_style="standard",
            basket_rail_count=1,
            seat_angle_deg=15.0,
        )
        assert node["_head_outer_diameter"] > self.stone_d

    def test_prong_head_outer_diameter_formula(self):
        """_head_outer_diameter = round(stone_diameter + 2 * prong_wire_diameter, 4)."""
        WIRE_D = 0.6
        node = build_prong_head_node(
            node_id="prong-002",
            stone_diameter=self.stone_d,
            prong_count=6,
            prong_wire_diameter=WIRE_D,
            prong_height=1.4,
            head_style="trellis",
            basket_rail_count=2,
            seat_angle_deg=15.0,
        )
        expected = round(self.stone_d + 2 * WIRE_D, 4)
        assert node["_head_outer_diameter"] == pytest.approx(expected, abs=1e-4)

    def test_prong_head_stores_correct_stone_diameter(self):
        node = build_prong_head_node(
            node_id="prong-003",
            stone_diameter=self.stone_d,
            prong_count=4,
            prong_wire_diameter=0.5,
            prong_height=1.4,
            head_style="standard",
            basket_rail_count=1,
            seat_angle_deg=15.0,
        )
        assert node["stone_diameter"] == pytest.approx(self.stone_d, rel=1e-9)
        assert node["prong_count"] == 4

    def test_bezel_outer_diameter_is_stone_plus_two_walls(self):
        """_outer_diameter = round(stone_diameter + 2 × wall_thickness, 4)."""
        WALL = 0.5
        node = build_bezel_node(
            node_id="bezel-001",
            stone_diameter=self.stone_d,
            wall_thickness=WALL,
            bezel_height=2.0,
            bearing_ledge_height=0.8,
            bezel_style="full",
            partial_opening_deg=0.0,
            taper_angle_deg=0.0,
        )
        expected_outer = round(self.stone_d + 2 * WALL, 4)
        assert node["_outer_diameter"] == pytest.approx(expected_outer, abs=1e-4)

    def test_bezel_inner_diameter_equals_stone_diameter(self):
        """_inner_diameter (bezel bore) must match stone girdle (rounded to 4dp)."""
        node = build_bezel_node(
            node_id="bezel-002",
            stone_diameter=self.stone_d,
            wall_thickness=0.4,
            bezel_height=1.8,
            bearing_ledge_height=0.7,
            bezel_style="tapered",
            partial_opening_deg=0.0,
            taper_angle_deg=5.0,
        )
        assert node["_inner_diameter"] == pytest.approx(round(self.stone_d, 4), abs=1e-4)

    def test_channel_node_length_equals_count_times_pitch(self):
        d = 2.0
        count = 7
        pitch = 2.2
        node = build_channel_node(
            node_id="chan-001",
            stone_diameter=d,
            stone_count=count,
            stone_spacing=pitch,
            rail_height=1.5,
            rail_thickness=0.5,
            floor_thickness=0.4,
        )
        assert node["_channel_length"] == pytest.approx(count * pitch, rel=1e-6)

    def test_prong_head_tool_runner_ok(self):
        ctx, store, fid = _make_ctx()
        result = _run(run_jewelry_create_prong_head(
            ctx,
            json.dumps({
                "file_id": str(fid),
                "stone_diameter": self.stone_d,
                "prong_count": 4,
                "prong_wire_diameter": 0.6,
                "prong_height": 1.5,
            }).encode(),
        ))
        assert _tool_ok(result)
        assert result["op"] == "jewelry_prong_head"
        assert result["stone_diameter"] == pytest.approx(self.stone_d, rel=1e-4)

    def test_bezel_tool_runner_ok(self):
        ctx, store, fid = _make_ctx()
        result = _run(run_jewelry_create_bezel(
            ctx,
            json.dumps({
                "file_id": str(fid),
                "stone_diameter": self.stone_d,
                "wall_thickness": 0.5,
                "bezel_height": 2.0,
                "bearing_ledge_height": 0.7,
            }).encode(),
        ))
        assert _tool_ok(result)
        assert result["op"] == "jewelry_bezel"
        assert result["stone_diameter"] == pytest.approx(self.stone_d, rel=1e-4)


# ============================================================================
# 4. Ring shank sizing — inner diameter matches ring size
# ============================================================================

class TestRingShank:
    """Step 4: size the shank and verify diameter consistency."""

    def test_us_size_7_diameter_in_standard_range(self):
        """US size 7 inner diameter ≈ 17.35 mm (industry standard)."""
        d = ring_size_to_diameter("us", RING_SIZE_US)
        assert 16.5 < d < 18.0, f"US size 7 diameter {d:.3f} mm outside expected range"

    def test_us_size_formula_exact(self):
        """Verify formula: ID = intercept + slope × size."""
        d = ring_size_to_diameter("us", RING_SIZE_US)
        expected = _US_ID_INTERCEPT + _US_ID_SLOPE * RING_SIZE_US
        assert d == pytest.approx(expected, rel=1e-9)

    def test_us_round_trip(self):
        """ring_diameter_to_size(ring_size_to_diameter(s)) ≈ s for US."""
        for size in [5, 6, 7, 8, 9, 10]:
            d = ring_size_to_diameter("us", size)
            back = ring_diameter_to_size("us", d)
            assert back == pytest.approx(size, abs=0.25)  # nearest half-size

    def test_uk_size_n_diameter_in_range(self):
        d = ring_size_to_diameter("uk", "N")
        # UK N ≈ circumference 54.4 mm → diameter ≈ 17.32 mm
        assert 16.0 < d < 19.0

    def test_eu_size_is_circumference_over_pi(self):
        """EU size is the circumference in mm; diameter = circ / π."""
        for circ in [49.0, 54.0, 59.0]:
            d = ring_size_to_diameter("eu", circ)
            assert d == pytest.approx(circ / _PI, rel=1e-6)

    def test_compute_shank_inner_diameter_matches_size_lookup(self):
        params = compute_shank_params(RING_SIZE_US, system="us")
        expected_id = ring_size_to_diameter("us", RING_SIZE_US)
        assert params["inner_diameter_mm"] == pytest.approx(expected_id, rel=1e-6)

    def test_compute_shank_outer_diameter_is_inner_plus_two_walls(self):
        t = 1.8
        params = compute_shank_params(RING_SIZE_US, system="us", thickness=t)
        id_mm = params["inner_diameter_mm"]
        od_mm = params["outer_diameter_mm"]
        assert od_mm == pytest.approx(id_mm + 2 * t, rel=1e-6)

    def test_compute_shank_circumference_is_pi_times_id(self):
        params = compute_shank_params(RING_SIZE_US, system="us")
        circ = params["circumference_mm"]
        id_mm = params["inner_diameter_mm"]
        assert circ == pytest.approx(_PI * id_mm, rel=1e-6)

    def test_shank_tool_runner_ok(self):
        ctx, store, fid = _make_ctx()
        result = _run(run_jewelry_create_ring_shank(
            ctx,
            json.dumps({
                "file_id": str(fid),
                "ring_size": RING_SIZE_US,
                "system": "us",
                "band_width": 4.0,
                "thickness": 1.8,
                "profile": "comfort_fit",
            }).encode(),
        ))
        assert _tool_ok(result)
        assert result["op"] == "ring_shank"

    def test_shank_tool_inner_diameter_consistent_with_size(self):
        ctx, store, fid = _make_ctx()
        result = _run(run_jewelry_create_ring_shank(
            ctx,
            json.dumps({
                "file_id": str(fid),
                "ring_size": RING_SIZE_US,
                "system": "us",
                "band_width": 4.0,
                "thickness": 1.8,
            }).encode(),
        ))
        expected_id = ring_size_to_diameter("us", RING_SIZE_US)
        assert result["inner_diameter_mm"] == pytest.approx(expected_id, rel=1e-4)

    def test_ring_size_tool_runner_forward_lookup(self):
        ctx, _, _ = _make_ctx()
        result = _run(run_jewelry_ring_size_to_diameter(
            ctx,
            json.dumps({"system": "us", "size": 7}).encode(),
        ))
        assert _tool_ok(result)
        d = result["inner_diameter_mm"]
        assert d == pytest.approx(ring_size_to_diameter("us", 7), rel=1e-6)


# ============================================================================
# 5. Pieces — pendant and earrings
# ============================================================================

class TestPieces:
    """Step 5: composite piece builders return sane geometry."""

    def test_pendant_centre_stone_diameter_stored(self):
        stone_d = mm_from_carat(STONE_CUT, STONE_CARAT)
        params = compute_pendant_params(
            style="solitaire_drop",
            width_mm=12.0,
            height_mm=20.0,
            thickness_mm=2.0,
            centre_stone_diameter_mm=stone_d,
        )
        assert params["centre_stone_diameter_mm"] == pytest.approx(stone_d, rel=1e-4)

    def test_pendant_height_exceeds_width(self):
        params = compute_pendant_params(width_mm=10.0, height_mm=18.0)
        assert params["height_mm"] > params["width_mm"]

    def test_pendant_thickness_stored(self):
        params = compute_pendant_params(thickness_mm=1.5)
        assert params["thickness_mm"] == pytest.approx(1.5, rel=1e-6)

    def test_earring_stud_post_length_positive(self):
        params = compute_earring_params(style="stud", post_length_mm=10.0)
        assert params["post_length_mm"] > 0

    def test_earring_drop_length_stored(self):
        params = compute_earring_params(style="drop", drop_length_mm=25.0)
        assert params["drop_length_mm"] == pytest.approx(25.0, rel=1e-6)


# ============================================================================
# 6. Metal weight + casting cost — volume-proportionality
# ============================================================================

class TestMetalWeight:
    """Step 6: verify weight math and volume proportionality."""

    @staticmethod
    def _shank_volume() -> float:
        """Analytic hollow-cylinder volume of a US-7 comfort-fit ring shank."""
        id_mm = ring_size_to_diameter("us", 7)
        od_mm = id_mm + 2 * 1.8
        band_w = 4.0
        return math.pi * ((od_mm / 2) ** 2 - (id_mm / 2) ** 2) * band_w

    def test_shank_volume_in_expected_range(self):
        vol = self._shank_volume()
        assert 100 < vol < 2000, f"Shank volume {vol:.1f} mm³ outside expected range"

    def test_metal_weight_18k_formula(self):
        """mass = density × volume_cm³."""
        vol = self._shank_volume()
        result = metal_weight(vol, metal=METAL_KEY)
        density = METAL_DENSITY_G_CM3[METAL_KEY]
        expected_g = density * vol / 1000.0
        assert result["grams"] == pytest.approx(expected_g, rel=1e-6)

    def test_metal_weight_18k_in_physical_range(self):
        """18k gold shank ~4–14 g for a narrow band."""
        vol = self._shank_volume()
        result = metal_weight(vol, metal=METAL_KEY)
        assert 2.0 < result["grams"] < 20.0

    def test_metal_weight_scales_linearly_with_volume(self):
        vol = self._shank_volume()
        w1 = metal_weight(vol, metal=METAL_KEY)["grams"]
        w2 = metal_weight(2 * vol, metal=METAL_KEY)["grams"]
        assert w2 == pytest.approx(2 * w1, rel=1e-9)

    def test_casting_weight_gross_exceeds_net(self):
        vol = self._shank_volume()
        net_g = metal_weight(vol, metal=METAL_KEY)["grams"]
        cast = casting_weight(net_g, casting_allowance_pct=15.0)
        assert cast["gross_grams"] > cast["net_grams"]
        assert cast["allowance_grams"] == pytest.approx(net_g * 0.15, rel=1e-6)

    def test_casting_cost_total_breakdown(self):
        """total_cost = gross × price + labor + finishing."""
        vol = self._shank_volume()
        labor = 120.0
        finish = 35.0
        result = casting_cost(
            vol,
            metal=METAL_KEY,
            metal_price_per_gram=METAL_PPG,
            labor=labor,
            finishing=finish,
        )
        expected_metal = result["gross_grams"] * METAL_PPG
        assert result["metal_cost"] == pytest.approx(expected_metal, rel=1e-6)
        assert result["total_cost"] == pytest.approx(expected_metal + labor + finish, rel=1e-6)

    def test_casting_cost_zero_price_gives_zero_metal_cost(self):
        vol = self._shank_volume()
        result = casting_cost(vol, metal=METAL_KEY, metal_price_per_gram=0.0)
        assert result["metal_cost"] == 0.0
        assert result["gross_grams"] > 0  # weight still computed

    def test_platinum_heavier_than_18k_gold_same_volume(self):
        """Platinum 950 (21.4 g/cm³) heavier than 18k yellow (15.58 g/cm³)."""
        vol = self._shank_volume()
        g_gold = metal_weight(vol, metal="18k_yellow")["grams"]
        g_plat = metal_weight(vol, metal="platinum_950")["grams"]
        assert g_plat > g_gold


# ============================================================================
# 7. Full jeweller's quote — multi-stone, labour, markup consistency
# ============================================================================

class TestJewelleryQuote:
    """Step 7: full quote combines metal + stone + labour; totals must add up."""

    @staticmethod
    def _vol():
        id_mm = ring_size_to_diameter("us", 7)
        od_mm = id_mm + 2 * 1.8
        return math.pi * ((od_mm / 2) ** 2 - (id_mm / 2) ** 2) * 4.0

    def test_quote_totals_add_up(self):
        """total == subtotal + markup_amount; subtotal == metal + stone + labour."""
        stones = [{"cut": STONE_CUT, "carat": STONE_CARAT, "price_per_carat": 800.0}]
        q = jewelry_quote(
            volume_mm3=self._vol(),
            metal=METAL_KEY,
            metal_price_per_gram=METAL_PPG,
            stones=stones,
            bench_hours=2.0,
            hourly_rate=80.0,
            setting_type="prong",
            markup_pct=20.0,
        )
        assert q["subtotal"] == pytest.approx(
            q["metal_cost"] + q["stone_cost"] + q["labour_total"], rel=1e-5
        )
        assert q["markup_amount"] == pytest.approx(q["subtotal"] * 0.20, rel=1e-5)
        assert q["total"] == pytest.approx(q["subtotal"] + q["markup_amount"], rel=1e-5)

    def test_quote_total_increases_with_markup(self):
        vol = self._vol()
        q0  = jewelry_quote(vol, metal=METAL_KEY, metal_price_per_gram=METAL_PPG, markup_pct=0)
        q20 = jewelry_quote(vol, metal=METAL_KEY, metal_price_per_gram=METAL_PPG, markup_pct=20)
        assert q20["total"] > q0["total"]

    def test_quote_stone_cost_matches_standalone_line_items(self):
        stones = [
            {"cut": STONE_CUT,  "carat": STONE_CARAT, "price_per_carat": 800.0},
            {"cut": "princess",  "carat": 0.10,        "price_per_carat": 200.0, "count": 6},
        ]
        q = jewelry_quote(
            volume_mm3=self._vol(),
            metal=METAL_KEY,
            metal_price_per_gram=METAL_PPG,
            stones=stones,
        )
        standalone = stone_cost_line_items(stones)
        assert q["stone_cost"] == pytest.approx(standalone["total_cost"], rel=1e-9)

    def test_quote_hallmark_for_18k_is_750(self):
        q = jewelry_quote(self._vol(), metal="18k_yellow", metal_price_per_gram=METAL_PPG)
        assert q["hallmark"] == 750

    def test_quote_with_price_preset_gives_nonzero_metal_cost(self):
        q = jewelry_quote(
            volume_mm3=self._vol(),
            metal=METAL_KEY,
            metal_price_per_gram=0.0,
            price_preset="usd_2024_approx",
        )
        assert q["metal_cost"] > 0, "Price preset should populate a non-zero metal cost"

    def test_stone_cost_line_items_single_stone(self):
        stones = [{"cut": "round_brilliant", "carat": 1.0, "price_per_carat": 5000.0}]
        result = stone_cost_line_items(stones)
        assert result["total_cost"] == pytest.approx(5000.0, rel=1e-9)
        assert result["total_carats"] == pytest.approx(1.0, rel=1e-9)
        assert result["total_stones"] == 1

    def test_labour_cost_bench_hours_scales_linearly(self):
        l1 = labour_cost(bench_hours=1.0, hourly_rate=100.0)
        l2 = labour_cost(bench_hours=3.0, hourly_rate=100.0)
        # Key is 'bench_labour_cost' in the returned dict
        assert l2["bench_labour_cost"] == pytest.approx(3 * l1["bench_labour_cost"], rel=1e-6)

    def test_labour_total_equals_bench_plus_setting_plus_finishing(self):
        l = labour_cost(bench_hours=2.0, hourly_rate=100.0)
        expected = l["bench_labour_cost"] + l["setting_cost"] + l["finishing_cost"]
        assert l["total_labour"] == pytest.approx(expected, rel=1e-9)


# ============================================================================
# 8. Casting export — manifest physics
# ============================================================================

class TestCastingExport:
    """Step 8: casting manifest values are internally consistent."""

    VOL = 500.0  # mm³

    def test_summary_est_metal_grams_matches_formula(self):
        summary = casting_export_summary("18k_yellow", self.VOL, thickness_mm=1.8)
        expected_g = METAL_DENSITY_G_CM3["18k_yellow"] * self.VOL / 1000.0
        assert summary["est_metal_grams"] == pytest.approx(expected_g, rel=1e-4)

    def test_pour_grams_exceeds_net_grams(self):
        summary = casting_export_summary("18k_yellow", self.VOL)
        assert summary["est_pour_grams_with_sprue"] > summary["est_metal_grams"]

    def test_sprue_count_one_for_small_piece(self):
        """Volume < 500 mm³ → 1 sprue."""
        summary = casting_export_summary("18k_yellow", 200.0)
        assert summary["sprue_count"] == 1

    def test_sprue_count_two_for_medium_large_piece(self):
        """Volume > 2000 mm³ → 2 sprues."""
        summary = casting_export_summary("18k_yellow", 2500.0)
        assert summary["sprue_count"] == 2

    def test_shrinkage_pct_positive_for_18k(self):
        s = get_shrinkage_pct("18k_yellow")
        assert 0.5 < s < 5.0, f"Shrinkage {s}% outside expected 0.5–5%"

    def test_apply_shrinkage_scale_wax_larger_than_finished(self):
        """Wax pattern must be larger than the finished dimension."""
        finished_mm = 17.35
        shrinkage = get_shrinkage_pct("18k_yellow")
        wax_mm = apply_shrinkage_scale(finished_mm, shrinkage)
        assert wax_mm > finished_mm

    def test_apply_shrinkage_scale_increases_with_shrinkage_pct(self):
        d = 17.35
        w1 = apply_shrinkage_scale(d, 1.0)
        w2 = apply_shrinkage_scale(d, 2.0)
        assert w2 > w1

    def test_estimate_pour_grams_scales_with_sprue_count(self):
        net = 5.0
        p1 = estimate_pour_grams(net, 1)
        p2 = estimate_pour_grams(net, 2)
        p3 = estimate_pour_grams(net, 3)
        assert p3 > p2 > p1 > net

    def test_gemstone_refs_stored_in_summary(self):
        refs = ["gem-001", "gem-002"]
        summary = casting_export_summary("18k_yellow", self.VOL, gemstone_refs=refs)
        assert summary["gemstones_excluded"] == refs

    def test_stl_bytes_none_without_occ(self):
        """Without pythonOCC installed stl_bytes is None."""
        summary = casting_export_summary("platinum_950", self.VOL)
        assert summary["stl_bytes"] is None


# ============================================================================
# 9. Templates — list + instantiate
# ============================================================================

class TestTemplates:
    """Step 9: template library returns valid recipes."""

    def test_list_returns_nonempty(self):
        templates = list_templates()
        assert len(templates) > 0

    def test_list_has_required_fields(self):
        for t in list_templates():
            for field in ("template_id", "name", "category", "metal", "component_count"):
                assert field in t, f"Template missing field: {field}"

    def test_ring_category_filter(self):
        rings = list_templates(category="rings")
        assert all(t["category"] == "rings" for t in rings)
        assert len(rings) > 0

    def test_get_template_by_id(self):
        first_id = list_templates()[0]["template_id"]
        t = get_template(first_id)
        assert t is not None
        assert t["template_id"] == first_id

    def test_get_template_unknown_returns_none(self):
        assert get_template("no-such-template-xyz") is None

    def test_instantiate_returns_recipe_with_components(self):
        tid = list_templates()[0]["template_id"]
        recipe = instantiate(tid)
        assert recipe is not None
        assert "components" in recipe

    def test_instantiate_override_ring_size(self):
        rings = list_templates(category="rings")
        if not rings:
            pytest.skip("No ring templates available")
        tid = rings[0]["template_id"]
        recipe = instantiate(tid, overrides={"ring_size": 9})
        assert recipe["ring_size"] == 9

    def test_tool_list_runner_ok(self):
        ctx, _, _ = _make_ctx()
        result = _run(run_list_jewelry_templates(ctx, b"{}"))
        assert _tool_ok(result)
        assert len(result["templates"]) > 0

    def test_tool_instantiate_runner_ok(self):
        ctx, _, _ = _make_ctx()
        tid = list_templates()[0]["template_id"]
        result = _run(run_instantiate_jewelry_template(
            ctx, json.dumps({"template_id": tid}).encode()
        ))
        assert _tool_ok(result)
        assert "components" in result


# ============================================================================
# 10. Cross-tool consistency — end-to-end solitaire ring workflow
# ============================================================================

class TestEndToEndSolitaire:
    """
    Drive a realistic solitaire ring workflow and assert cross-tool consistency.

    Workflow:
      a. Pick stone  → gemstone_proportions
      b. Cut seat    → seat_geometry
      c. Size ring   → ring_size_to_diameter
      d. Build shank → compute_shank_params
      e. Compute volume (analytic hollow cylinder)
      f. Metal weight  → metal_weight
      g. Full quote  → jewelry_quote
      h. Cast export → casting_export_summary
    """

    def setup_method(self):
        # a. Stone
        self.props = gemstone_proportions(STONE_CUT, carat=STONE_CARAT)
        self.stone_d = self.props.diameter_mm

        # b. Seat
        self.seat = seat_geometry(
            cut=STONE_CUT,
            diameter_mm=self.stone_d,
            pavilion_angle_deg=self.props.pavilion_angle_deg,
            pavilion_depth_pct=self.props.pavilion_depth_pct,
            girdle_pct=self.props.girdle_pct,
            crown_angle_deg=self.props.crown_angle_deg,
        )

        # c. Ring size
        self.ring_id_mm = ring_size_to_diameter("us", RING_SIZE_US)

        # d. Shank
        self.shank = compute_shank_params(RING_SIZE_US, system="us", thickness=1.8)

        # e. Volume (analytic hollow cylinder, band_width = 4 mm)
        od = self.shank["outer_diameter_mm"]
        id_ = self.shank["inner_diameter_mm"]
        bw = 4.0
        self.vol_mm3 = math.pi * ((od / 2) ** 2 - (id_ / 2) ** 2) * bw

        # f. Metal weight
        self.weight = metal_weight(self.vol_mm3, metal=METAL_KEY)

        # g. Quote
        self.stones_spec = [
            {"cut": STONE_CUT, "carat": STONE_CARAT, "price_per_carat": 800.0}
        ]
        self.quote = jewelry_quote(
            volume_mm3=self.vol_mm3,
            metal=METAL_KEY,
            metal_price_per_gram=METAL_PPG,
            stones=self.stones_spec,
            bench_hours=2.0,
            hourly_rate=80.0,
            setting_type="prong",
            markup_pct=15.0,
        )

        # h. Cast export
        self.export = casting_export_summary(METAL_KEY, self.vol_mm3, thickness_mm=1.8)

    # ---- Seat ↔ Stone cross-check ----

    def test_seat_bore_is_stone_girdle_plus_clearance(self):
        """girdle_radius_mm = round(stone_r + default_clearance, 4)."""
        DEFAULT_CLEARANCE = 0.05
        expected_r = round(self.stone_d / 2.0 + DEFAULT_CLEARANCE, 4)
        assert self.seat["girdle_radius_mm"] == pytest.approx(expected_r, abs=1e-4)

    def test_seat_bore_larger_than_stone(self):
        assert self.seat["girdle_radius_mm"] > self.stone_d / 2.0

    # ---- Shank ↔ Ring-size cross-check ----

    def test_shank_inner_diameter_matches_ring_size(self):
        assert self.shank["inner_diameter_mm"] == pytest.approx(self.ring_id_mm, rel=1e-6)

    def test_shank_outer_diameter_formula(self):
        od = self.shank["outer_diameter_mm"]
        id_ = self.shank["inner_diameter_mm"]
        assert od == pytest.approx(id_ + 2 * 1.8, rel=1e-6)

    # ---- Metal weight consistency ----

    def test_weight_density_times_volume(self):
        density = METAL_DENSITY_G_CM3[METAL_KEY]
        expected = density * self.vol_mm3 / 1000.0
        assert self.weight["grams"] == pytest.approx(expected, rel=1e-6)

    # ---- Quote internal consistency ----

    def test_quote_metal_cost_is_gross_times_price(self):
        gross_g = self.quote["gross_grams"]
        assert self.quote["metal_cost"] == pytest.approx(gross_g * METAL_PPG, rel=1e-5)

    def test_quote_net_grams_matches_metal_weight(self):
        assert self.quote["net_grams"] == pytest.approx(self.weight["grams"], rel=1e-5)

    def test_quote_gross_exceeds_net(self):
        assert self.quote["gross_grams"] > self.quote["net_grams"]

    def test_quote_total_above_metal_cost(self):
        """Total must exceed metal cost alone (stones + labour + markup add to it)."""
        assert self.quote["total"] > self.quote["metal_cost"]

    def test_quote_stone_carat_preserved(self):
        """Carat stored in quote's stone line items matches input."""
        line = self.quote["stones"]["line_items"][0]
        assert line["carat_each"] == pytest.approx(STONE_CARAT, rel=1e-6)

    # ---- Quote ↔ Export cross-check ----

    def test_export_net_grams_matches_quote_net(self):
        """Both quote and export derive net_grams from the same density formula."""
        assert self.export["est_metal_grams"] == pytest.approx(
            self.quote["net_grams"], rel=1e-4
        )

    def test_export_pour_exceeds_net(self):
        assert self.export["est_pour_grams_with_sprue"] > self.export["est_metal_grams"]

    # ---- Setting ↔ Stone cross-check ----

    def test_prong_head_outer_larger_than_stone(self):
        node = build_prong_head_node(
            node_id="e2e-prong",
            stone_diameter=self.stone_d,
            prong_count=4,
            prong_wire_diameter=0.6,
            prong_height=1.5,
            head_style="standard",
            basket_rail_count=1,
            seat_angle_deg=15.0,
        )
        assert node["_head_outer_diameter"] > self.stone_d

    def test_bezel_outer_larger_than_stone(self):
        node = build_bezel_node(
            node_id="e2e-bezel",
            stone_diameter=self.stone_d,
            wall_thickness=0.5,
            bezel_height=2.0,
            bearing_ledge_height=0.7,
            bezel_style="full",
            partial_opening_deg=0.0,
            taper_angle_deg=0.0,
        )
        assert node["_outer_diameter"] > self.stone_d

    # ---- Density table consistency ----

    def test_density_consistent_between_metal_cost_and_casting_export(self):
        """METAL_DENSITY_G_CM3 table must agree between metal_cost and casting_export."""
        from kerf_cad_core.jewelry.casting_export import (
            METAL_DENSITY_G_CM3 as ce_density,
        )
        for key in ["18k_yellow", "platinum_950", "sterling_925", "18k_white"]:
            assert ce_density[key] == METAL_DENSITY_G_CM3[key], (
                f"Density mismatch for {key}: "
                f"metal_cost={METAL_DENSITY_G_CM3[key]}, "
                f"casting_export={ce_density[key]}"
            )

    def test_shank_profile_in_valid_set(self):
        from kerf_cad_core.jewelry.ring import _VALID_PROFILES
        assert self.shank["profile"] in _VALID_PROFILES
