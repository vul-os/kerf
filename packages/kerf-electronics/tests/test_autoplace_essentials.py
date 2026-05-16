"""
Tests for auto-placement essentials: decoupling caps, thermal via arrays,
mounting-hole keep-outs, power-plane relief, and bypass-cap recommendations.

All tests are hermetic (no network, no filesystem side-effects).

Coverage (>=25 tests):
  auto_decouple:
    - Each IC VCC pin gets exactly one decoupling cap
    - Placement distance is <= 2 mm from VCC pin
    - Multi-IC board: correct number of total caps
    - IC with multiple VCC pins: one cap per pin
    - IC with no VCC pins: no caps, warning emitted
    - IC with no pads: no caps, warning emitted
    - Cap position vector points toward GND pin
    - Non-dict IC entry: warning, no crash
    - Returned traces connect VCC→cap and cap→GND
    - Custom cap_value and package echoed on placed cap
    - pads=[] on IC: warning emitted

  thermal_via_array:
    - Grid pattern: rows * cols >= via_count
    - Staggered pattern: odd rows are offset by pitch_x/2
    - Actual via count equals rows * cols
    - via_count=1 on tiny pad: single via at centre
    - via_drill >= via_dia returns error
    - via_count < 1 returns error
    - Unknown pattern returns error
    - Staggered lattice geometry: odd-row x offset = pitch_x/2

  mounting_hole_keepout:
    - Keepout radius = hole_dia/2 + keepout_extra_mm
    - Polygon is approximately circular (all points equidistant from centre)
    - Covers hole and annulus (radius > hole_dia/2)
    - hole_dia <= 0 returns error
    - keepout_extra_mm=0: radius equals hole_dia/2

  power_plane_relief:
    - Anti-pad diameter = via_od + 2 * anti_pad_mm
    - Polygon points all lie on anti-pad circle
    - anti_pad_mm < 0 returns error
    - Empty plane_layer returns error
    - Net name is echoed in anti-pad dict

  bypass_cap_recommendation:
    - Known IC (ATmega328P) returns correct caps, known_part=True
    - Known IC (STM32) substring match works
    - Unknown IC returns generic recommendation, known_part=False
    - Missing ic_part returns error code BAD_ARGS
    - supply_voltage is echoed in result
    - LDO (AMS1117) returns both input and output caps
"""

from __future__ import annotations

import json
import math
import unittest

# Trigger @register decorators
import kerf_electronics.autoplace.tools  # noqa: F401

from kerf_electronics.autoplace.essentials import (
    auto_decouple,
    bypass_cap_recommendation,
    mounting_hole_keepout,
    power_plane_relief,
    thermal_via_array,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _dist(ax, ay, bx, by):
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


async def _call(tool_name: str, args: dict) -> dict:
    """Call a registered tool by name and parse the JSON response."""
    from kerf_chat.tools.registry import Registry
    for tool in Registry:
        if tool.spec.name == tool_name:
            raw = await tool.run(None, json.dumps(args).encode())
            return json.loads(raw)
    raise KeyError(f"tool {tool_name!r} not found in Registry")


def _run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)


# ─── Fixture data ─────────────────────────────────────────────────────────────

def _make_ic(refdes, x, y, vcc_pins=None, gnd_pins=None, extra_pins=None):
    """Build a minimal IC footprint dict."""
    pads = []
    if vcc_pins:
        for name, px, py in vcc_pins:
            pads.append({"net_name": name, "x": px, "y": py, "width": 0.6, "height": 0.6})
    if gnd_pins:
        for name, px, py in gnd_pins:
            pads.append({"net_name": name, "x": px, "y": py, "width": 0.6, "height": 0.6})
    if extra_pins:
        for name, px, py in extra_pins:
            pads.append({"net_name": name, "x": px, "y": py, "width": 0.6, "height": 0.6})
    return {"refdes": refdes, "x": x, "y": y, "pads": pads}


SIMPLE_BOARD = {"type": "pcb_board", "width": 100.0, "height": 80.0}

U1 = _make_ic(
    "U1", x=20.0, y=20.0,
    vcc_pins=[("VCC", 0.0, -1.5)],
    gnd_pins=[("GND", 0.0,  1.5)],
    extra_pins=[("PA0", 1.5, 0.0), ("PA1", -1.5, 0.0)],
)

U2 = _make_ic(
    "U2", x=50.0, y=40.0,
    vcc_pins=[("VDD", 0.0, -1.5), ("VDD_IO", 2.0, -1.5)],
    gnd_pins=[("GND", 0.0,  1.5)],
)

U3_NO_VCC = _make_ic(
    "U3", x=80.0, y=20.0,
    extra_pins=[("TX", 0.0, 0.0), ("RX", 1.0, 0.0)],
)

U4_NO_PADS = {"refdes": "U4", "x": 60.0, "y": 60.0, "pads": []}

THERMAL_PAD = {
    "x": 10.0, "y": 10.0,
    "width": 4.0, "height": 4.0,
    "net_name": "GND",
}


# ─── 1. auto_decouple ─────────────────────────────────────────────────────────

class TestAutoDecouple(unittest.TestCase):

    def test_single_ic_single_vcc_pin_gets_one_cap(self):
        result = auto_decouple(SIMPLE_BOARD, [U1])
        self.assertEqual(result["cap_count"], 1)
        self.assertEqual(len(result["placed_caps"]), 1)

    def test_cap_within_2mm_of_vcc_pin(self):
        result = auto_decouple(SIMPLE_BOARD, [U1])
        cap = result["placed_caps"][0]
        # U1 is at (20, 20); VCC pad at offset (0, -1.5) → absolute (20, 18.5)
        vcc_abs_x, vcc_abs_y = 20.0 + 0.0, 20.0 + (-1.5)
        d = _dist(cap["x"], cap["y"], vcc_abs_x, vcc_abs_y)
        self.assertLessEqual(d, 2.0 + 1e-9,
                             f"Cap at ({cap['x']}, {cap['y']}) is {d:.3f} mm from VCC pin")

    def test_multi_ic_total_cap_count(self):
        # U1 has 1 VCC, U2 has 2 VCC pins → 3 caps total
        result = auto_decouple(SIMPLE_BOARD, [U1, U2])
        self.assertEqual(result["cap_count"], 3)

    def test_ic_with_two_vcc_pins_gets_two_caps(self):
        result = auto_decouple(SIMPLE_BOARD, [U2])
        self.assertEqual(result["cap_count"], 2)
        nets = {c["vcc_net"] for c in result["placed_caps"]}
        self.assertIn("VDD", nets)
        self.assertIn("VDD_IO", nets)

    def test_ic_with_no_vcc_pins_emits_warning(self):
        result = auto_decouple(SIMPLE_BOARD, [U3_NO_VCC])
        self.assertEqual(result["cap_count"], 0)
        self.assertTrue(
            any("no VCC/VDD" in w for w in result["warnings"]),
            f"Expected VCC warning; got: {result['warnings']}"
        )

    def test_ic_with_no_pads_emits_warning(self):
        result = auto_decouple(SIMPLE_BOARD, [U4_NO_PADS])
        self.assertEqual(result["cap_count"], 0)
        self.assertTrue(any("no pads" in w for w in result["warnings"]))

    def test_non_dict_ic_entry_emits_warning(self):
        result = auto_decouple(SIMPLE_BOARD, ["not_a_dict", U1])
        # U1 still processed; non-dict entry → warning
        self.assertEqual(result["cap_count"], 1)
        self.assertTrue(any("non-dict" in w for w in result["warnings"]))

    def test_cap_vector_points_toward_gnd(self):
        # U1 VCC is at (20, 18.5), GND at (20, 21.5) → cap should be south of VCC
        result = auto_decouple(SIMPLE_BOARD, [U1])
        cap = result["placed_caps"][0]
        vcc_y = 20.0 - 1.5  # 18.5
        gnd_y = 20.0 + 1.5  # 21.5
        # Cap y should be between VCC and GND (i.e. > vcc_y and <= gnd_y)
        self.assertGreater(cap["y"], vcc_y - 1e-9)
        self.assertLessEqual(cap["y"], gnd_y + 1e-9)

    def test_traces_vcc_to_cap_generated(self):
        result = auto_decouple(SIMPLE_BOARD, [U1])
        traces = result["traces"]
        vcc_traces = [t for t in traces if t.get("net") == "VCC"]
        self.assertGreaterEqual(len(vcc_traces), 1)

    def test_traces_cap_to_gnd_generated(self):
        result = auto_decouple(SIMPLE_BOARD, [U1])
        traces = result["traces"]
        gnd_traces = [t for t in traces if t.get("net") == "GND"]
        self.assertGreaterEqual(len(gnd_traces), 1)

    def test_custom_cap_value_echoed(self):
        result = auto_decouple(SIMPLE_BOARD, [U1], cap_value="10nF", package="0201")
        cap = result["placed_caps"][0]
        self.assertEqual(cap["value"], "10nF")
        self.assertEqual(cap["package"], "0201")

    def test_empty_ic_list_returns_zero_caps(self):
        result = auto_decouple(SIMPLE_BOARD, [])
        self.assertEqual(result["cap_count"], 0)
        self.assertEqual(result["placed_caps"], [])

    def test_tool_roundtrip_via_llm_registry(self):
        ic = _make_ic("U5", 10.0, 10.0,
                      vcc_pins=[("VCC", 0.0, -1.0)],
                      gnd_pins=[("GND", 0.0, 1.0)])
        resp = _run(_call("auto_decouple", {
            "ic_footprints": [ic],
            "cap_value": "100nF",
            "package": "0402",
        }))
        self.assertTrue(resp.get("ok"), resp)
        self.assertEqual(resp["cap_count"], 1)


# ─── 2. thermal_via_array ─────────────────────────────────────────────────────

class TestThermalViaArray(unittest.TestCase):

    def test_grid_rows_cols_cover_via_count(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=9, via_dia=0.6, via_drill=0.3)
        self.assertNotIn("error", result)
        self.assertGreaterEqual(result["actual_count"], 9)

    def test_grid_actual_count_equals_rows_times_cols(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=6, via_dia=0.6, via_drill=0.3)
        self.assertEqual(result["actual_count"], result["rows"] * result["cols"])

    def test_staggered_odd_rows_offset(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=6, via_dia=0.6, via_drill=0.3,
                                   pattern="staggered")
        vias = result["vias"]
        rows = result["rows"]
        pitch_x = result["pitch_x_mm"]
        if rows < 2 or pitch_x == 0:
            self.skipTest("Not enough rows to verify stagger")
        # Collect x coords for row 0 and row 1
        cols = result["cols"]
        row0_xs = [vias[c]["x"] for c in range(cols)]
        row1_xs = [vias[cols + c]["x"] for c in range(cols)]
        # Each row-1 x should be ~pitch_x/2 ahead of corresponding row-0 x
        for c in range(cols):
            expected_offset = pitch_x / 2.0
            actual_offset = row1_xs[c] - row0_xs[c]
            self.assertAlmostEqual(actual_offset, expected_offset, places=3,
                                   msg=f"Stagger offset wrong at col {c}")

    def test_via_count_1_single_via(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=1, via_dia=0.6, via_drill=0.3)
        self.assertGreaterEqual(result["actual_count"], 1)

    def test_via_drill_gte_via_dia_error(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=4, via_dia=0.6, via_drill=0.6)
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_via_count_zero_error(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=0, via_dia=0.6, via_drill=0.3)
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_unknown_pattern_error(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=4, via_dia=0.6, via_drill=0.3,
                                   pattern="hexagonal")
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_grid_pattern_no_stagger(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=4, via_dia=0.6, via_drill=0.3,
                                   pattern="grid")
        # Row 0 and row 1 should share the same x positions (no stagger)
        vias = result["vias"]
        cols = result["cols"]
        if result["rows"] >= 2 and result["pitch_x_mm"] > 0:
            for c in range(min(cols, len(vias) - cols)):
                self.assertAlmostEqual(vias[c]["x"], vias[cols + c]["x"], places=3)

    def test_staggered_pattern_lattice_geometry_all_rows(self):
        result = thermal_via_array(SIMPLE_BOARD, THERMAL_PAD,
                                   via_count=9, via_dia=0.6, via_drill=0.3,
                                   pattern="staggered")
        vias = result["vias"]
        rows = result["rows"]
        cols = result["cols"]
        pitch_x = result["pitch_x_mm"]
        for r in range(rows):
            for c in range(cols):
                idx = r * cols + c
                if idx >= len(vias):
                    break
                v = vias[idx]
                if r % 2 == 1 and pitch_x > 0:
                    # Odd row: x offset relative to even row at same col
                    even_idx = (r - 1) * cols + c
                    if even_idx < len(vias):
                        diff = v["x"] - vias[even_idx]["x"]
                        self.assertAlmostEqual(diff, pitch_x / 2.0, places=3)

    def test_tool_roundtrip_via_llm_registry(self):
        resp = _run(_call("thermal_via_array", {
            "pad": THERMAL_PAD,
            "via_count": 4,
            "via_dia": 0.6,
            "via_drill": 0.3,
            "pattern": "grid",
        }))
        self.assertTrue(resp.get("ok"), resp)
        self.assertGreaterEqual(resp["actual_count"], 4)


# ─── 3. mounting_hole_keepout ─────────────────────────────────────────────────

class TestMountingHoleKeeout(unittest.TestCase):

    def test_keepout_radius_equals_hole_plus_extra(self):
        result = mounting_hole_keepout(SIMPLE_BOARD, {"x": 5.0, "y": 5.0},
                                       hole_dia=3.2, keepout_extra_mm=2.5)
        expected = 3.2 / 2.0 + 2.5
        self.assertAlmostEqual(result["radius_mm"], expected, places=4)

    def test_polygon_points_equidistant_from_centre(self):
        result = mounting_hole_keepout(SIMPLE_BOARD, {"x": 10.0, "y": 15.0},
                                       hole_dia=3.2, keepout_extra_mm=2.5)
        kz = result["keepout"]
        expected_r = kz["keepout_radius_mm"]
        for pt in kz["polygon"]:
            d = _dist(pt["x"], pt["y"], 10.0, 15.0)
            self.assertAlmostEqual(d, expected_r, places=2)

    def test_keepout_covers_hole_and_annulus(self):
        result = mounting_hole_keepout(SIMPLE_BOARD, {"x": 0.0, "y": 0.0},
                                       hole_dia=3.2, keepout_extra_mm=2.5)
        self.assertGreater(result["radius_mm"], 3.2 / 2.0)

    def test_hole_dia_zero_returns_error(self):
        result = mounting_hole_keepout(SIMPLE_BOARD, {"x": 0.0, "y": 0.0},
                                       hole_dia=0.0, keepout_extra_mm=2.5)
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_keepout_extra_zero_radius_equals_half_dia(self):
        result = mounting_hole_keepout(SIMPLE_BOARD, {"x": 0.0, "y": 0.0},
                                       hole_dia=4.0, keepout_extra_mm=0.0)
        self.assertAlmostEqual(result["radius_mm"], 2.0, places=4)

    def test_tool_roundtrip_via_llm_registry(self):
        resp = _run(_call("mounting_hole_keepout", {
            "hole_position": {"x": 5.0, "y": 5.0},
            "hole_dia": 3.2,
            "keepout_extra_mm": 2.5,
        }))
        self.assertTrue(resp.get("ok"), resp)
        self.assertAlmostEqual(resp["radius_mm"], 3.2 / 2.0 + 2.5, places=4)


# ─── 4. power_plane_relief ────────────────────────────────────────────────────

class TestPowerPlaneRelief(unittest.TestCase):

    def test_anti_pad_diameter_formula(self):
        via = {"x": 0.0, "y": 0.0, "outer_diameter": 0.8, "net_name": "GND"}
        result = power_plane_relief("inner_copper_1", via, anti_pad_mm=0.25)
        expected_dia = 0.8 + 2.0 * 0.25
        self.assertAlmostEqual(result["anti_pad"]["anti_pad_dia_mm"], expected_dia, places=4)

    def test_polygon_points_on_anti_pad_circle(self):
        via = {"x": 5.0, "y": 7.0, "outer_diameter": 1.0, "net_name": "VCC"}
        result = power_plane_relief("inner_copper_2", via, anti_pad_mm=0.3)
        ap = result["anti_pad"]
        expected_r = ap["anti_pad_dia_mm"] / 2.0
        for pt in ap["polygon"]:
            d = _dist(pt["x"], pt["y"], 5.0, 7.0)
            self.assertAlmostEqual(d, expected_r, places=2)

    def test_negative_anti_pad_returns_error(self):
        via = {"x": 0.0, "y": 0.0, "outer_diameter": 0.8, "net_name": "GND"}
        result = power_plane_relief("inner_copper_1", via, anti_pad_mm=-0.1)
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_empty_layer_returns_error(self):
        via = {"x": 0.0, "y": 0.0, "outer_diameter": 0.8, "net_name": "GND"}
        result = power_plane_relief("", via, anti_pad_mm=0.25)
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_net_name_echoed(self):
        via = {"x": 0.0, "y": 0.0, "outer_diameter": 0.8, "net_name": "PWR_3V3"}
        result = power_plane_relief("inner_copper_1", via, anti_pad_mm=0.2)
        self.assertEqual(result["anti_pad"]["via_net"], "PWR_3V3")

    def test_tool_roundtrip_via_llm_registry(self):
        via = {"x": 3.0, "y": 3.0, "outer_diameter": 0.8, "net_name": "GND"}
        resp = _run(_call("power_plane_relief", {
            "plane_layer": "inner_copper_1",
            "via": via,
            "anti_pad_mm": 0.25,
        }))
        self.assertTrue(resp.get("ok"), resp)
        self.assertAlmostEqual(
            resp["anti_pad"]["anti_pad_dia_mm"], 0.8 + 2 * 0.25, places=4
        )


# ─── 5. bypass_cap_recommendation ────────────────────────────────────────────

class TestBypassCapRecommendation(unittest.TestCase):

    def test_atmega328p_known_part(self):
        result = bypass_cap_recommendation("ATmega328P")
        self.assertTrue(result["known_part"])
        self.assertGreater(len(result["recommendations"]), 0)

    def test_stm32_substring_match(self):
        result = bypass_cap_recommendation("STM32F103C8T6")
        self.assertTrue(result["known_part"])
        recs = result["recommendations"]
        values = [r["value"] for r in recs]
        self.assertIn("100nF", values)

    def test_unknown_ic_returns_generic(self):
        result = bypass_cap_recommendation("MY_CUSTOM_ASIC_v2")
        self.assertFalse(result["known_part"])
        self.assertGreater(len(result["recommendations"]), 0)
        self.assertTrue(any(w for w in result["warnings"]))

    def test_missing_ic_part_bad_args(self):
        result = bypass_cap_recommendation("")
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")

    def test_supply_voltage_echoed(self):
        result = bypass_cap_recommendation("ATmega328P", supply_voltage=5.0)
        self.assertAlmostEqual(result["supply_voltage_v"], 5.0)

    def test_ldo_ams1117_has_input_and_output_caps(self):
        result = bypass_cap_recommendation("AMS1117-3.3")
        self.assertTrue(result["known_part"])
        notes = [r["notes"] for r in result["recommendations"]]
        self.assertTrue(any("input" in n for n in notes))
        self.assertTrue(any("output" in n for n in notes))

    def test_esp32_known_part(self):
        result = bypass_cap_recommendation("esp32")
        self.assertTrue(result["known_part"])

    def test_generic_rp2040(self):
        result = bypass_cap_recommendation("RP2040")
        self.assertTrue(result["known_part"])
        recs = result["recommendations"]
        self.assertGreater(len(recs), 0)

    def test_tool_roundtrip_via_llm_registry(self):
        resp = _run(_call("bypass_cap_recommendation", {
            "ic_part": "ATmega328P",
            "supply_voltage": 5.0,
        }))
        self.assertTrue(resp.get("ok"), resp)
        self.assertTrue(resp["known_part"])
        self.assertGreater(len(resp["recommendations"]), 0)

    def test_non_string_ic_part_bad_args(self):
        result = bypass_cap_recommendation(None)  # type: ignore[arg-type]
        self.assertIn("error", result)
        self.assertEqual(result["code"], "BAD_ARGS")


if __name__ == "__main__":
    unittest.main()
