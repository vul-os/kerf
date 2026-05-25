"""
Dispatch tests for the 3 new textiles LLM tools:
  textiles_cut_room / textiles_etextiles / textiles_sustainability
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_textiles.tools import (
    textiles_cut_room_spec, run_textiles_cut_room,
    textiles_etextiles_spec, run_textiles_etextiles,
    textiles_sustainability_spec, run_textiles_sustainability,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Spec sanity
# ---------------------------------------------------------------------------

class TestSpecs:
    def test_all_specs_have_names(self):
        for spec in [textiles_cut_room_spec, textiles_etextiles_spec, textiles_sustainability_spec]:
            assert spec["name"].startswith("textiles_")
            assert len(spec["description"]) > 20
            assert "type" in spec["input_schema"]


# ---------------------------------------------------------------------------
# textiles_cut_room
# ---------------------------------------------------------------------------

class TestTextilesCutRoom:
    def test_single_piece_fits(self):
        result = _run(run_textiles_cut_room({
            "pieces": [{"name": "front", "w": 300, "h": 500}],
            "rolls": [{"name": "R1", "width": 1500}],
        }))
        assert result["ok"] is True
        assert result["utilization"] > 0

    def test_oversized_piece_unplaced(self):
        result = _run(run_textiles_cut_room({
            "pieces": [{"name": "huge", "w": 2000, "h": 500}],
            "rolls": [{"name": "R1", "width": 1500}],
        }))
        assert result["ok"] is False
        assert "huge" in result["unplaced"]

    def test_multi_piece_utilisation(self):
        pieces = [{"name": f"p{i}", "w": 100, "h": 200} for i in range(5)]
        result = _run(run_textiles_cut_room({
            "pieces": pieces,
            "rolls": [{"name": "R1", "width": 600}],
        }))
        assert result["ok"] is True
        assert result["utilization"] > 0.5

    def test_empty_pieces_ok(self):
        result = _run(run_textiles_cut_room({
            "pieces": [],
            "rolls": [{"name": "R1", "width": 1500}],
        }))
        assert result["ok"] is True

    def test_no_rolls_fails(self):
        result = _run(run_textiles_cut_room({
            "pieces": [{"name": "a", "w": 100, "h": 100}],
            "rolls": [],
        }))
        assert result["ok"] is False

    def test_grain_angle_respected(self):
        result = _run(run_textiles_cut_room({
            "pieces": [{"name": "p", "w": 100, "h": 200, "grain_angles": [0]}],
            "rolls": [{"name": "R1", "width": 400}],
        }))
        assert result["ok"] is True
        # Piece must be placed at angle 0 only
        placements = result["layouts"][0]["placements"]
        for pl in placements:
            assert pl["angle"] == 0.0


# ---------------------------------------------------------------------------
# textiles_etextiles
# ---------------------------------------------------------------------------

class TestTextilesEtextiles:
    def test_heater_i2r(self):
        result = _run(run_textiles_etextiles({
            "mode": "heater",
            "yarn_resistance_per_metre": 10.0,  # 10 Ω/m
            "length_m": 1.0,
            "current_a": 0.5,
        }))
        assert result["ok"] is True
        assert abs(result["resistance_ohm"] - 10.0) < 1e-6
        assert abs(result["power_w"] - 0.25 * 10.0) < 1e-6  # I²R = 0.25 * 10
        assert abs(result["voltage_drop_v"] - 5.0) < 1e-6   # IR = 0.5 * 10

    def test_heater_longer_trace(self):
        result = _run(run_textiles_etextiles({
            "mode": "heater",
            "yarn_resistance_per_metre": 5.0,
            "length_m": 2.0,
            "current_a": 1.0,
        }))
        assert abs(result["resistance_ohm"] - 10.0) < 1e-6   # 5*2
        assert abs(result["power_w"] - 10.0) < 1e-6           # 1²*10

    def test_led_layout_parallel_series(self):
        # 3 parallel × 2 series NeoPixel-class LEDs, Vf=3.2V, If=20mA
        result = _run(run_textiles_etextiles({
            "mode": "led_layout",
            "vsupply": 5.0,
            "n_parallel": 3,
            "n_series": 1,
            "led_vf": 3.2,
            "led_if_ma": 20.0,
            "r_series_ohm": 90.0,  # (5.0-3.2)/0.09 ≈ 20mA per branch
        }))
        assert result["ok"] is True
        assert result["n_branches"] == 3
        assert result["total_leds"] == 3
        # Each branch: (5.0-3.2)/90 ≈ 0.02 A
        for i_branch in result["branch_currents_a"]:
            assert abs(i_branch - 0.02) < 0.001

    def test_bad_mode_returns_error(self):
        result = _run(run_textiles_etextiles({"mode": "submarine"}))
        assert result["ok"] is False
        assert "error" in result

    def test_missing_heater_params_returns_error(self):
        result = _run(run_textiles_etextiles({"mode": "heater"}))
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# textiles_sustainability
# ---------------------------------------------------------------------------

class TestTextilesSustainability:
    def test_organic_cotton_higher_than_conventional(self):
        organic = _run(run_textiles_sustainability({
            "material_mix": {"cotton_organic": 1.0},
        }))
        conventional = _run(run_textiles_sustainability({
            "material_mix": {"cotton_conventional": 1.0},
        }))
        assert organic["ok"] is True
        assert conventional["ok"] is True
        assert organic["sustainability_score"] > conventional["sustainability_score"]

    def test_score_in_range(self):
        result = _run(run_textiles_sustainability({
            "material_mix": {"cotton_conventional": 0.5, "polyester_recycled": 0.5},
            "garment_mass_kg": 0.25,
        }))
        assert result["ok"] is True
        assert 0.0 <= result["sustainability_score"] <= 100.0

    def test_breakdown_fractions_sum_to_one(self):
        result = _run(run_textiles_sustainability({
            "material_mix": {"cotton_organic": 0.6, "polyester_recycled": 0.4},
        }))
        total_frac = sum(b["mass_fraction"] for b in result["breakdown"])
        assert abs(total_frac - 1.0) < 1e-4

    def test_bad_mix_not_summing_to_one(self):
        result = _run(run_textiles_sustainability({
            "material_mix": {"cotton_organic": 0.3, "cotton_conventional": 0.3},
        }))
        assert result["ok"] is False
        assert "error" in result

    def test_unknown_material_returns_error(self):
        result = _run(run_textiles_sustainability({
            "material_mix": {"unobtainium_fiber": 1.0},
        }))
        assert result["ok"] is False
