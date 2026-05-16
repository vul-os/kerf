"""
Tests for kerf_cad_core.jewelry.bangle

Pure-Python tests (always run — no OCC required):
  - WRIST_SIZE_TABLE: all entries, inner circumference ↔ diameter round-trips
  - wrist_size_to_inner_circumference: valid + invalid keys
  - inner_circumference_to_diameter: formula
  - oval_area: formula (π a b)
  - oval_perimeter: Ramanujan approximation; round trip ratio check
  - cushion_perimeter: formula; corner_radius=0 degenerates to square
  - cross_section_properties: A and I for all six profiles; dimensional checks
  - twisted_wire_pitch: formula consistency with helix geometry
  - comfort_fit_chord: inner_diameter == circumference/π
  - stone_station_positions: angles, spacing, radius
  - cuff_forming_circumference: spring-back reduces mandrel; gap narrowing
  - compute_closed_bangle_params: mass = ρ·V; inner circumference matches table
  - compute_closed_bangle_params: oval area formula
  - compute_open_cuff_params: active arc, gap correctness, volume fraction
  - compute_torque_params: helix angle formula; finial volume; mass = ρ·V
  - compute_hinged_bangle_params: volume, hinge spec, comfort chord
  - LLM tool specs: names, required fields present
  - bangle_size tool runner: valid wrist size, explicit circumference, errors
"""

from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.jewelry.bangle import (
    WRIST_SIZE_TABLE,
    WRIST_SIZE_LABELS,
    SPRING_BACK_DEG,
    _VALID_INNER_PROFILES,
    _VALID_CROSS_SECTIONS,
    _VALID_FINIALS,
    _VALID_CLASP_STYLES,
    wrist_size_to_inner_circumference,
    inner_circumference_to_diameter,
    oval_area,
    oval_perimeter,
    cushion_perimeter,
    cross_section_properties,
    twisted_wire_pitch,
    comfort_fit_chord,
    stone_station_positions,
    cuff_forming_circumference,
    compute_closed_bangle_params,
    compute_open_cuff_params,
    compute_torque_params,
    compute_hinged_bangle_params,
    bangle_volume_mm3,
    _bangle_size_spec,
    _closed_bangle_spec,
    _open_cuff_spec,
    _torque_spec,
    _hinged_bangle_spec,
    run_jewelry_bangle_size,
    run_jewelry_create_closed_bangle,
    run_jewelry_create_open_cuff,
    run_jewelry_create_torque,
    run_jewelry_create_hinged_bangle,
)
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3

_PI = math.pi


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

    class _Ctx:
        async def read_file(self, fid, *a, **kw):
            if str(fid) == str(file_id):
                return store["content"], None
            return None, "not found"

        async def write_file(self, fid, content, *a, **kw):
            if str(fid) == str(file_id):
                store["content"] = content
                return None
            return "not found"

    return _Ctx(), project_id, file_id, store


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. WRIST_SIZE_TABLE entries
# ---------------------------------------------------------------------------

def test_wrist_size_table_has_standard_sizes():
    for size in ["XS", "S", "M", "L", "XL", "XXL"]:
        assert size in WRIST_SIZE_TABLE
        assert WRIST_SIZE_TABLE[size] > 0


def test_wrist_size_table_monotonically_increasing():
    sizes_in_order = ["XS", "S", "M", "L", "XL", "XXL"]
    values = [WRIST_SIZE_TABLE[s] for s in sizes_in_order]
    for i in range(1, len(values)):
        assert values[i] > values[i - 1], (
            f"Wrist size table not monotonic: {sizes_in_order[i]} ({values[i]}) "
            f"<= {sizes_in_order[i-1]} ({values[i-1]})"
        )


def test_wrist_size_m_is_165():
    # M = 165 mm per Pandora / Rio Grande standard
    assert WRIST_SIZE_TABLE["M"] == pytest.approx(165.0)


def test_wrist_size_labels_cover_all_sizes():
    for k in WRIST_SIZE_TABLE:
        assert k in WRIST_SIZE_LABELS


# ---------------------------------------------------------------------------
# 2. wrist_size_to_inner_circumference
# ---------------------------------------------------------------------------

def test_wrist_size_to_inner_circumference_valid():
    circ = wrist_size_to_inner_circumference("M")
    assert circ == pytest.approx(165.0)


def test_wrist_size_case_insensitive():
    assert wrist_size_to_inner_circumference("m") == pytest.approx(165.0)
    assert wrist_size_to_inner_circumference("l") == pytest.approx(175.0)


def test_wrist_size_invalid_raises():
    with pytest.raises(ValueError, match="Unknown wrist size"):
        wrist_size_to_inner_circumference("HUGE")


# ---------------------------------------------------------------------------
# 3. inner_circumference_to_diameter
# ---------------------------------------------------------------------------

def test_inner_circumference_to_diameter_formula():
    circ = 165.0
    d = inner_circumference_to_diameter(circ)
    assert d == pytest.approx(circ / _PI, rel=1e-9)


def test_inner_circumference_to_diameter_round_trip():
    d = 52.5
    circ = _PI * d
    assert inner_circumference_to_diameter(circ) == pytest.approx(d, rel=1e-9)


def test_inner_circumference_to_diameter_invalid():
    with pytest.raises(ValueError):
        inner_circumference_to_diameter(0.0)
    with pytest.raises(ValueError):
        inner_circumference_to_diameter(-5.0)


# ---------------------------------------------------------------------------
# 4. oval_area
# ---------------------------------------------------------------------------

def test_oval_area_formula():
    major = 60.0
    minor = 50.0
    expected = _PI * (major / 2.0) * (minor / 2.0)
    assert oval_area(major, minor) == pytest.approx(expected, rel=1e-9)


def test_oval_area_circle_degenerate():
    d = 52.0
    # When major == minor, it's a circle: area = π r²
    expected = _PI * (d / 2.0) ** 2
    assert oval_area(d, d) == pytest.approx(expected, rel=1e-9)


def test_oval_area_invalid():
    with pytest.raises(ValueError):
        oval_area(0, 10)
    with pytest.raises(ValueError):
        oval_area(10, -1)


# ---------------------------------------------------------------------------
# 5. oval_perimeter (Ramanujan second approximation)
# ---------------------------------------------------------------------------

def test_oval_perimeter_circle_degenerate():
    d = 52.0
    # Circle circumference = π d
    expected = _PI * d
    p = oval_perimeter(d, d)
    assert p == pytest.approx(expected, rel=1e-4)


def test_oval_perimeter_greater_than_minor_axis_circle():
    # For a non-circular oval, perimeter > perimeter of minor-axis circle
    major = 70.0
    minor = 50.0
    p = oval_perimeter(major, minor)
    minor_circ = _PI * minor
    major_circ = _PI * major
    assert minor_circ < p < major_circ + minor_circ


def test_oval_perimeter_invalid():
    with pytest.raises(ValueError):
        oval_perimeter(0, 10)


# ---------------------------------------------------------------------------
# 6. cushion_perimeter
# ---------------------------------------------------------------------------

def test_cushion_perimeter_zero_corner_is_square():
    side = 60.0
    p = cushion_perimeter(side, 0.0)
    assert p == pytest.approx(4.0 * side, rel=1e-9)


def test_cushion_perimeter_max_corner_is_circle():
    # corner_radius = side/2 → cushion degenerates to a circle of diameter = side
    side = 60.0
    p = cushion_perimeter(side, side / 2.0)
    assert p == pytest.approx(_PI * side, rel=1e-6)


def test_cushion_perimeter_typical():
    side = 60.0
    r = side * 0.15
    p = cushion_perimeter(side, r)
    # Must be between square perimeter and circle perimeter
    assert 4 * (side - 2 * r) < p < 4 * side


def test_cushion_perimeter_invalid_corner():
    with pytest.raises(ValueError):
        cushion_perimeter(60.0, 40.0)  # corner_radius > side/2


# ---------------------------------------------------------------------------
# 7. cross_section_properties — area and I_xx
# ---------------------------------------------------------------------------

def test_cross_section_round_wire_area():
    r = 2.0
    props = cross_section_properties("round_wire", 2 * r)
    assert props["area_mm2"] == pytest.approx(_PI * r ** 2, rel=1e-6)


def test_cross_section_round_wire_I():
    r = 2.0
    props = cross_section_properties("round_wire", 2 * r)
    assert props["I_xx_mm4"] == pytest.approx(_PI * r ** 4 / 4.0, rel=1e-6)


def test_cross_section_half_round_area():
    r = 2.0
    props = cross_section_properties("half_round", 2 * r)
    assert props["area_mm2"] == pytest.approx(_PI * r ** 2 / 2.0, rel=1e-6)


def test_cross_section_half_round_I():
    r = 2.0
    props = cross_section_properties("half_round", 2 * r)
    assert props["I_xx_mm4"] == pytest.approx(_PI * r ** 4 / 8.0, rel=1e-6)


def test_cross_section_square_area():
    s = 4.0
    props = cross_section_properties("square", s)
    assert props["area_mm2"] == pytest.approx(s ** 2, rel=1e-6)


def test_cross_section_square_I():
    s = 4.0
    props = cross_section_properties("square", s)
    assert props["I_xx_mm4"] == pytest.approx(s ** 4 / 12.0, rel=1e-6)


def test_cross_section_knife_edge_area():
    w, h = 5.0, 3.0
    props = cross_section_properties("knife_edge", w, h)
    assert props["area_mm2"] == pytest.approx(0.5 * w * h, rel=1e-6)


def test_cross_section_knife_edge_I():
    w, h = 5.0, 3.0
    props = cross_section_properties("knife_edge", w, h)
    assert props["I_xx_mm4"] == pytest.approx(w * h ** 3 / 36.0, rel=1e-6)


def test_cross_section_d_shape_area_positive():
    props = cross_section_properties("d_shape", 6.0, 4.0)
    assert props["area_mm2"] > 0


def test_cross_section_twisted_wire_same_as_round():
    # twisted_wire shares area/I with round_wire
    w = 4.0
    rw = cross_section_properties("round_wire", w)
    tw = cross_section_properties("twisted_wire", w)
    assert tw["area_mm2"] == pytest.approx(rw["area_mm2"], rel=1e-9)
    assert tw["I_xx_mm4"] == pytest.approx(rw["I_xx_mm4"], rel=1e-9)


def test_cross_section_invalid():
    with pytest.raises(ValueError, match="Unknown cross_section"):
        cross_section_properties("hexagonal", 5.0)


def test_cross_section_invalid_width():
    with pytest.raises(ValueError):
        cross_section_properties("round_wire", 0.0)


# ---------------------------------------------------------------------------
# 8. twisted_wire_pitch  (helix formula)
# ---------------------------------------------------------------------------

def test_twisted_wire_pitch_formula():
    d = 2.0
    angle = 30.0
    pitch = twisted_wire_pitch(d, angle)
    expected = _PI * d / math.tan(math.radians(angle))
    assert pitch == pytest.approx(expected, rel=1e-9)


def test_twisted_wire_pitch_45_deg():
    d = 3.0
    pitch = twisted_wire_pitch(d, 45.0)
    # tan(45) = 1, so pitch = π d
    assert pitch == pytest.approx(_PI * d, rel=1e-9)


def test_twisted_wire_pitch_invalid_angle():
    with pytest.raises(ValueError):
        twisted_wire_pitch(2.0, 0.0)
    with pytest.raises(ValueError):
        twisted_wire_pitch(2.0, 90.0)
    with pytest.raises(ValueError):
        twisted_wire_pitch(2.0, -5.0)


def test_twisted_wire_pitch_invalid_diameter():
    with pytest.raises(ValueError):
        twisted_wire_pitch(0.0, 30.0)


# ---------------------------------------------------------------------------
# 9. comfort_fit_chord
# ---------------------------------------------------------------------------

def test_comfort_fit_chord_diameter():
    circ = 165.0
    chord = comfort_fit_chord(circ)
    # Values are rounded to 3 dp in the return dict; use abs tolerance
    assert chord["inner_diameter_mm"] == pytest.approx(circ / _PI, abs=1e-2)
    assert chord["comfort_chord_mm"] == pytest.approx(circ / _PI, abs=1e-2)


def test_comfort_fit_chord_note_contains_diameter():
    chord = comfort_fit_chord(165.0)
    assert "52" in chord["knuckle_clearance_note"]  # ~52.5 mm


def test_comfort_fit_chord_invalid():
    with pytest.raises(ValueError):
        comfort_fit_chord(0.0)


# ---------------------------------------------------------------------------
# 10. stone_station_positions
# ---------------------------------------------------------------------------

def test_stone_stations_full_circle_spacing():
    stations = stone_station_positions(4, 165.0, 4.0)
    assert len(stations) == 4
    spacing = 360.0 / 4
    for i, s in enumerate(stations):
        assert s["station_index"] == i
        # angles should be equally spaced midpoints
        expected = spacing / 2 + i * spacing
        assert s["angle_deg"] == pytest.approx(expected, rel=1e-6)


def test_stone_stations_radius_positive():
    stations = stone_station_positions(3, 165.0, 4.0)
    for s in stations:
        assert s["radius_mm"] > 0


def test_stone_stations_arc_subset():
    # Setting only on top 120 degrees
    stations = stone_station_positions(3, 165.0, 4.0, arc_deg_start=0, arc_deg_end=120)
    for s in stations:
        assert 0 <= s["angle_deg"] <= 120


def test_stone_stations_invalid_n():
    with pytest.raises(ValueError):
        stone_station_positions(0, 165.0, 4.0)


# ---------------------------------------------------------------------------
# 11. cuff_forming_circumference  (spring-back)
# ---------------------------------------------------------------------------

def test_cuff_spring_back_mandrel_smaller():
    # Mandrel must be smaller than target to compensate for spring-back
    result = cuff_forming_circumference(165.0, "18k_yellow", 30.0)
    assert result["mandrel_diameter_mm"] < result["target_inner_diameter_mm"]
    assert result["mandrel_circumference_mm"] < result["target_inner_circumference_mm"]


def test_cuff_spring_back_gap_narrows():
    # After release, gap narrows slightly
    result = cuff_forming_circumference(165.0, "sterling_925", 30.0)
    assert result["gap_angle_after_forming_deg"] < result["gap_angle_deg"]


def test_cuff_spring_back_active_arc():
    result = cuff_forming_circumference(165.0, "18k_yellow", 30.0)
    assert result["active_arc_deg"] == pytest.approx(330.0, rel=1e-6)


def test_cuff_spring_back_uses_alloy_table():
    # Different metals should give different mandrel sizes
    r1 = cuff_forming_circumference(165.0, "titanium", 30.0)
    r2 = cuff_forming_circumference(165.0, "fine_silver", 30.0)
    # Titanium has higher spring-back → smaller mandrel
    assert r1["mandrel_diameter_mm"] < r2["mandrel_diameter_mm"]


def test_cuff_spring_back_invalid_gap():
    with pytest.raises(ValueError):
        cuff_forming_circumference(165.0, "18k_yellow", 0.0)
    with pytest.raises(ValueError):
        cuff_forming_circumference(165.0, "18k_yellow", 360.0)


# ---------------------------------------------------------------------------
# 12. compute_closed_bangle_params — mass = ρ·V
# ---------------------------------------------------------------------------

def test_closed_bangle_mass_equals_rho_times_volume():
    metal = "18k_yellow"
    rho = METAL_DENSITY_G_CM3[metal]  # g/cm³
    params = compute_closed_bangle_params(
        inner_circumference_mm=165.0,
        cross_section="round_wire",
        cs_width_mm=4.0,
        metal=metal,
    )
    vol_cm3 = params["volume_mm3"] / 1000.0
    expected_g = rho * vol_cm3
    assert params["mass_g"] == pytest.approx(expected_g, rel=1e-4)


def test_closed_bangle_inner_circumference_matches_m_size():
    params = compute_closed_bangle_params(
        inner_circumference_mm=WRIST_SIZE_TABLE["M"],
        cross_section="round_wire",
        cs_width_mm=4.0,
    )
    assert params["inner_circumference_mm"] == pytest.approx(
        WRIST_SIZE_TABLE["M"], rel=1e-6
    )


def test_closed_bangle_volume_positive():
    params = compute_closed_bangle_params(165.0, "round_wire", 4.0)
    assert params["volume_mm3"] > 0


def test_closed_bangle_oval_area_in_path():
    # Oval path length must be longer than round path for same circumference
    p_round = compute_closed_bangle_params(165.0, "round_wire", 4.0, inner_profile="round")
    p_oval = compute_closed_bangle_params(165.0, "round_wire", 4.0, inner_profile="oval")
    # Oval perimeter > circle perimeter of same 'width' due to ellipse shape
    # (the oval major axis is larger than the circle diameter)
    assert p_oval["path_length_mm"] != p_round["path_length_mm"]


def test_closed_bangle_stone_stations():
    params = compute_closed_bangle_params(
        165.0, "round_wire", 4.0, n_stone_stations=5
    )
    assert len(params["stone_stations"]) == 5


def test_closed_bangle_invalid_inner_profile():
    with pytest.raises(ValueError, match="Unknown inner_profile"):
        compute_closed_bangle_params(165.0, "round_wire", 4.0, inner_profile="hexagon")


def test_closed_bangle_invalid_cross_section():
    with pytest.raises(ValueError, match="Unknown cross_section"):
        compute_closed_bangle_params(165.0, "hexagonal_wire", 4.0)


# ---------------------------------------------------------------------------
# 13. compute_open_cuff_params
# ---------------------------------------------------------------------------

def test_open_cuff_active_arc():
    gap = 30.0
    params = compute_open_cuff_params(165.0, gap_angle_deg=gap)
    assert params["active_arc_deg"] == pytest.approx(360.0 - gap, rel=1e-6)


def test_open_cuff_volume_fraction_of_closed():
    gap = 30.0
    p_closed = compute_closed_bangle_params(165.0, "round_wire", 4.0)
    p_open = compute_open_cuff_params(165.0, gap_angle_deg=gap)
    expected_frac = (360.0 - gap) / 360.0
    assert p_open["volume_mm3"] == pytest.approx(
        p_closed["volume_mm3"] * expected_frac, rel=1e-3
    )


def test_open_cuff_spring_back_included_when_metal_given():
    params = compute_open_cuff_params(165.0, metal="sterling_925")
    assert params["spring_back"] is not None
    assert params["spring_back"]["mandrel_diameter_mm"] > 0


def test_open_cuff_mass_equals_rho_times_volume():
    metal = "sterling_925"
    rho = METAL_DENSITY_G_CM3[metal]
    params = compute_open_cuff_params(165.0, metal=metal, gap_angle_deg=30.0)
    expected_g = rho * params["volume_mm3"] / 1000.0
    assert params["mass_g"] == pytest.approx(expected_g, rel=1e-4)


def test_open_cuff_invalid_gap():
    with pytest.raises(ValueError):
        compute_open_cuff_params(165.0, gap_angle_deg=360.0)


# ---------------------------------------------------------------------------
# 14. compute_torque_params — helix angle + mass
# ---------------------------------------------------------------------------

def test_torque_helix_angle_formula():
    # helix_angle = atan(twist_turns × 2π × arm_r / path_length)
    circ = 165.0
    cs_w = 5.0
    twist = 2.0
    params = compute_torque_params(
        inner_circumference_mm=circ,
        cs_width_mm=cs_w,
        twist_turns=twist,
    )
    arm_r = circ / (2.0 * _PI) + cs_w / 2.0
    path = params["path_length_mm"]
    expected_angle = math.degrees(math.atan(twist * 2.0 * _PI * arm_r / path))
    assert params["helix_angle_deg"] == pytest.approx(expected_angle, rel=1e-4)


def test_torque_mass_equals_rho_times_volume():
    metal = "platinum_950"
    rho = METAL_DENSITY_G_CM3[metal]
    params = compute_torque_params(
        inner_circumference_mm=165.0,
        cs_width_mm=5.0,
        metal=metal,
    )
    expected_g = rho * params["volume_total_mm3"] / 1000.0
    assert params["mass_g"] == pytest.approx(expected_g, rel=1e-4)


def test_torque_total_volume_includes_finials():
    params = compute_torque_params(165.0, cs_width_mm=5.0)
    assert params["volume_total_mm3"] > params["volume_arm_mm3"]
    assert params["volume_finials_mm3"] > 0


def test_torque_zero_twist():
    params = compute_torque_params(165.0, cs_width_mm=5.0, twist_turns=0.0)
    assert params["helix_angle_deg"] == pytest.approx(0.0)


def test_torque_finial_ball_volume_formula():
    cs_w = 5.0
    fin_d = cs_w * 1.5  # default
    r = fin_d / 2.0
    expected_vol_each = (4.0 / 3.0) * _PI * r ** 3
    params = compute_torque_params(165.0, cs_width_mm=cs_w, finial_style="ball")
    assert params["volume_finials_mm3"] == pytest.approx(2.0 * expected_vol_each, rel=1e-4)


def test_torque_invalid_finial():
    with pytest.raises(ValueError, match="Unknown finial_style"):
        compute_torque_params(165.0, finial_style="dragon_head_xyz")


# ---------------------------------------------------------------------------
# 15. compute_hinged_bangle_params
# ---------------------------------------------------------------------------

def test_hinged_bangle_comfort_chord():
    circ = 165.0
    params = compute_hinged_bangle_params(circ)
    # Rounded to 3 dp; use abs tolerance
    assert params["comfort_chord_mm"] == pytest.approx(circ / _PI, abs=1e-2)


def test_hinged_bangle_hinge_spec():
    params = compute_hinged_bangle_params(165.0)
    assert params["knuckle_count"] == 3
    assert params["hinge_pin_diameter_mm"] == pytest.approx(1.5, rel=1e-6)
    assert params["hinge_volume_mm3"] > 0


def test_hinged_bangle_total_volume_includes_hinge():
    params = compute_hinged_bangle_params(165.0)
    assert params["volume_total_mm3"] > params["volume_mm3"]


def test_hinged_bangle_mass_with_metal():
    metal = "14k_rose"
    rho = METAL_DENSITY_G_CM3[metal]
    params = compute_hinged_bangle_params(165.0, metal=metal)
    expected_g = rho * params["volume_total_mm3"] / 1000.0
    assert params["mass_g"] == pytest.approx(expected_g, rel=1e-4)


def test_hinged_bangle_clasp_style_stored():
    params = compute_hinged_bangle_params(165.0, clasp_style="tongue_groove")
    assert params["clasp_style"] == "tongue_groove"


def test_hinged_bangle_invalid_clasp():
    with pytest.raises(ValueError, match="Unknown clasp_style"):
        compute_hinged_bangle_params(165.0, clasp_style="mystery_clasp")


# ---------------------------------------------------------------------------
# 16. LLM tool specs
# ---------------------------------------------------------------------------

def test_bangle_size_spec_name():
    assert _bangle_size_spec.name == "jewelry_bangle_size"


def test_closed_bangle_spec_name():
    assert _closed_bangle_spec.name == "jewelry_create_closed_bangle"
    assert "file_id" in _closed_bangle_spec.input_schema.get("required", [])


def test_open_cuff_spec_name():
    assert _open_cuff_spec.name == "jewelry_create_open_cuff"
    assert "file_id" in _open_cuff_spec.input_schema.get("required", [])


def test_torque_spec_name():
    assert _torque_spec.name == "jewelry_create_torque"
    assert "file_id" in _torque_spec.input_schema.get("required", [])


def test_hinged_bangle_spec_name():
    assert _hinged_bangle_spec.name == "jewelry_create_hinged_bangle"
    assert "file_id" in _hinged_bangle_spec.input_schema.get("required", [])


# ---------------------------------------------------------------------------
# 17. Tool runner: run_jewelry_bangle_size
# ---------------------------------------------------------------------------

def test_bangle_size_runner_valid_wrist_size():
    result = run(run_jewelry_bangle_size(None, json.dumps({"wrist_size": "M"}).encode()))
    data = json.loads(result)
    assert "error" not in data, data
    assert data["inner_circumference_mm"] == pytest.approx(165.0, abs=1e-3)


def test_bangle_size_runner_explicit_circumference():
    result = run(
        run_jewelry_bangle_size(None, json.dumps({"inner_circumference_mm": 170.0}).encode())
    )
    data = json.loads(result)
    assert "error" not in data, data
    assert data["inner_diameter_mm"] == pytest.approx(170.0 / _PI, abs=1e-2)


def test_bangle_size_runner_no_args_error():
    result = run(run_jewelry_bangle_size(None, json.dumps({}).encode()))
    data = json.loads(result)
    assert "error" in data
    assert data["code"] == "BAD_ARGS"


def test_bangle_size_runner_invalid_size_error():
    result = run(
        run_jewelry_bangle_size(None, json.dumps({"wrist_size": "GIANT"}).encode())
    )
    data = json.loads(result)
    assert "error" in data
    assert data["code"] == "BAD_ARGS"


def test_bangle_size_runner_bad_json():
    result = run(run_jewelry_bangle_size(None, b"not json"))
    data = json.loads(result)
    assert "error" in data
    assert data["code"] == "BAD_ARGS"
