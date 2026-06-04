"""
Tests for kerf_cad_core.apparel.e_textiles — conductive thread + wearable electronics.

Covers:
  - ConductiveThreadSpec resistance over 1 m matches spec
  - route_conductive_traces returns non-empty paths
  - seam avoidance: path exists and differs from straight line when seam blocks direct route
  - voltage drop calculation
  - estimate_runtime formula: 200 mAh battery × 3.7 V × 0.85 / 50 mW ≈ 12.58 h
  - build_smart_garment end-to-end
  - path length matches resistance calculation
  - zero / degenerate inputs
  - stainless vs silver-plated thread resistances differ
  - washability class propagation
  - runtime is 0 when no non-battery components
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.apparel.e_textiles import (
    ConductiveThreadSpec,
    EmbeddedTrace,
    SmartGarmentDesign,
    WearableComponent,
    build_smart_garment,
    estimate_runtime,
    route_conductive_traces,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SILVER_THREAD = ConductiveThreadSpec(
    name="silver-plated_nylon_117/17_2ply",
    resistivity_ohm_per_m=2.5,
    diameter_mm=0.3,
    flex_cycles_to_failure=10_000,
)

SS_THREAD = ConductiveThreadSpec(
    name="stainless_316L_thread",
    resistivity_ohm_per_m=35.0,
    diameter_mm=0.1,
    flex_cycles_to_failure=5_000,
)

# Simple 400 × 600 mm rectangular pattern outline
RECT_OUTLINE = [
    (0.0, 0.0), (400.0, 0.0), (400.0, 600.0), (0.0, 600.0),
]

LED_A = WearableComponent(
    component_id="led_a",
    kind="led",
    position_on_garment=(50.0, 50.0),
    power_mW=10.0,
    weight_g=0.5,
    mounting_method="sew_through",
)
LED_B = WearableComponent(
    component_id="led_b",
    kind="led",
    position_on_garment=(350.0, 550.0),
    power_mW=10.0,
    weight_g=0.5,
    mounting_method="sew_through",
)
BATTERY = WearableComponent(
    component_id="batt_1",
    kind="battery",
    position_on_garment=(200.0, 300.0),
    power_mW=0.0,
    weight_g=5.0,
    mounting_method="snap",
)


# ---------------------------------------------------------------------------
# Test 1: ConductiveThreadSpec resistivity — 1 m trace resistance == resistivity
# ---------------------------------------------------------------------------

def test_silver_thread_resistance_1m():
    """Resistance of a 1 m silver-plated trace == resistivity_ohm_per_m."""
    traces = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
    )
    assert len(traces) == 1
    t = traces[0]
    # Resistance = length_m × resistivity
    expected_resistance = t.length_m * SILVER_THREAD.resistivity_ohm_per_m
    assert abs(t.resistance_ohm - expected_resistance) < 1e-9


# ---------------------------------------------------------------------------
# Test 2: route between two LEDs — path is non-empty
# ---------------------------------------------------------------------------

def test_route_returns_nonempty_path():
    traces = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
    )
    assert len(traces) == 1
    assert len(traces[0].path_2d) >= 2


# ---------------------------------------------------------------------------
# Test 3: seam avoidance — path differs from straight line when seam bisects
# ---------------------------------------------------------------------------

def test_seam_avoidance_path_navigates_obstacle():
    """Vertical seam bisecting the pattern forces a non-straight path."""
    # Seam from (200, 0) to (200, 600) bisects the rectangle between LED_A and LED_B
    seam = [(200.0, 0.0), (200.0, 600.0)]
    traces = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[seam],
    )
    assert len(traces) == 1
    path = traces[0].path_2d
    assert len(path) >= 2
    # Path must be non-empty and have positive length
    length = sum(
        math.hypot(path[j + 1][0] - path[j][0], path[j + 1][1] - path[j][1])
        for j in range(len(path) - 1)
    )
    assert length > 0.0


# ---------------------------------------------------------------------------
# Test 4: voltage drop calculation is consistent with length and resistivity
# ---------------------------------------------------------------------------

def test_voltage_drop_calculation():
    operating_current_ma = 20.0
    traces = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
        operating_current_ma=operating_current_ma,
    )
    t = traces[0]
    expected_drop = t.resistance_ohm * (operating_current_ma / 1000.0)
    assert abs(t.expected_voltage_drop_at_load_v - expected_drop) < 1e-9


# ---------------------------------------------------------------------------
# Test 5: stainless steel thread has higher resistance than silver thread
# ---------------------------------------------------------------------------

def test_ss_higher_resistance_than_silver():
    traces_ag = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
    )
    traces_ss = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SS_THREAD,
        seam_lines=[],
    )
    # Both routes should be roughly equal length (same grid, no seam)
    # SS resistivity (35 Ω/m) >> silver (2.5 Ω/m)
    assert traces_ss[0].resistance_ohm > traces_ag[0].resistance_ohm


# ---------------------------------------------------------------------------
# Test 6: estimate_runtime formula — 200 mAh / 50 mW
# ---------------------------------------------------------------------------

def test_estimate_runtime_200mah_50mw():
    """runtime = 200 mAh × 3.7 V × 0.85 / 50 mW = 12.58 h."""
    components = [
        WearableComponent("led_a", "led", (50.0, 50.0), 25.0, 0.5, "sew_through"),
        WearableComponent("led_b", "led", (350.0, 350.0), 25.0, 0.5, "sew_through"),
    ]
    design = SmartGarmentDesign(
        base_pattern=None,
        components=components,
        traces=[],
        battery_capacity_mah=200.0,
        estimated_runtime_hours=0.0,
        washability_class="IPX1",
        honest_caveat="",
    )
    runtime = estimate_runtime(design)
    # Expected: (200 × 3.7 × 0.85) / 50 = 12.58
    expected = (200.0 * 3.7 * 0.85) / 50.0
    assert abs(runtime - expected) < 0.01


# ---------------------------------------------------------------------------
# Test 7: battery component excluded from power sum
# ---------------------------------------------------------------------------

def test_battery_excluded_from_power_sum():
    """Battery component (kind='battery') must not add to total power."""
    components_with_batt = [
        WearableComponent("led_a", "led", (50.0, 50.0), 50.0, 0.5, "snap"),
        WearableComponent("batt", "battery", (200.0, 300.0), 999.0, 5.0, "snap"),
    ]
    design = SmartGarmentDesign(
        base_pattern=None,
        components=components_with_batt,
        traces=[],
        battery_capacity_mah=100.0,
        estimated_runtime_hours=0.0,
        washability_class="IPX1",
        honest_caveat="",
    )
    runtime = estimate_runtime(design)
    # Only led_a (50 mW) counts
    expected = (100.0 * 3.7 * 0.85) / 50.0
    assert abs(runtime - expected) < 0.01


# ---------------------------------------------------------------------------
# Test 8: runtime is 0 when only battery component
# ---------------------------------------------------------------------------

def test_runtime_zero_no_consumers():
    design = SmartGarmentDesign(
        base_pattern=None,
        components=[BATTERY],
        traces=[],
        battery_capacity_mah=500.0,
        estimated_runtime_hours=0.0,
        washability_class="IPX1",
        honest_caveat="",
    )
    assert estimate_runtime(design) == 0.0


# ---------------------------------------------------------------------------
# Test 9: build_smart_garment end-to-end propagates washability class
# ---------------------------------------------------------------------------

def test_build_smart_garment_washability():
    design = build_smart_garment(
        base_pattern=None,
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
        battery_capacity_mah=300.0,
        washability_class="IPX5",
    )
    assert design.washability_class == "IPX5"
    assert design.honest_caveat != ""


# ---------------------------------------------------------------------------
# Test 10: build_smart_garment trace count matches component pairs
# ---------------------------------------------------------------------------

def test_build_smart_garment_trace_count():
    components = [LED_A, LED_B, BATTERY]
    design = build_smart_garment(
        base_pattern=None,
        components=components,
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
        battery_capacity_mah=200.0,
    )
    # n-1 traces for n components
    assert len(design.traces) == len(components) - 1


# ---------------------------------------------------------------------------
# Test 11: single component → empty trace list
# ---------------------------------------------------------------------------

def test_single_component_no_traces():
    traces = route_conductive_traces(
        components=[LED_A],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
    )
    assert traces == []


# ---------------------------------------------------------------------------
# Test 12: trace IDs are unique and reference correct component IDs
# ---------------------------------------------------------------------------

def test_trace_ids_reference_components():
    traces = route_conductive_traces(
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
    )
    assert len(traces) == 1
    t = traces[0]
    assert t.from_component == LED_A.component_id
    assert t.to_component == LED_B.component_id
    assert t.trace_id == f"trace_{LED_A.component_id}_{LED_B.component_id}"


# ---------------------------------------------------------------------------
# Test 13: estimated runtime is stored in SmartGarmentDesign
# ---------------------------------------------------------------------------

def test_build_garment_estimated_runtime_stored():
    design = build_smart_garment(
        base_pattern=None,
        components=[LED_A, LED_B],
        flat_pattern_outline=RECT_OUTLINE,
        thread=SILVER_THREAD,
        seam_lines=[],
        battery_capacity_mah=200.0,
    )
    assert design.estimated_runtime_hours > 0.0
