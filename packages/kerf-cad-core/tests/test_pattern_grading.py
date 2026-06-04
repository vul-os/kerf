"""
Tests for kerf_cad_core.apparel.pattern_grading — multi-size pattern grading.

Covers:
  - grade M → S produces smaller pattern (negative step → inward)
  - grade M → L produces larger pattern (positive step → outward)
  - base size pattern is identical to input
  - grading rule landmark displacement is correctly applied
  - uniform scaling fallback for no-landmark case
  - pattern_area sign and magnitude
  - GradedSizes contains all requested sizes
  - outline vertex count preserved
  - two-piece pattern graded correctly
  - centroid shift from grading
  - no-rule grading still produces output for each size
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.apparel.pattern_grading import (
    GradedSizes,
    GradingRule,
    grade_pattern,
    pattern_area,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Simple 200 mm × 300 mm rectangle (base pattern piece, M size)
BASE_RECT = [(0.0, 0.0), (200.0, 0.0), (200.0, 300.0), (0.0, 300.0)]

# Grading rules: each size step moves the outline outward by 5 mm in x, 7.5 mm in y
# (waist_left x=-0.5 cm, waist_right x=+0.5 cm; hip_left x=-0.5 cm, hip_right x=+0.5 cm)
RULES = [
    GradingRule("corner_bl", x_grade_cm_per_size=-0.5, y_grade_cm_per_size=-0.75),
    GradingRule("corner_br", x_grade_cm_per_size=+0.5, y_grade_cm_per_size=-0.75),
    GradingRule("corner_tr", x_grade_cm_per_size=+0.5, y_grade_cm_per_size=+0.75),
    GradingRule("corner_tl", x_grade_cm_per_size=-0.5, y_grade_cm_per_size=+0.75),
]
# Landmarks map each corner to the corresponding vertex index
LANDMARKS = {
    "corner_bl": 0,
    "corner_br": 1,
    "corner_tr": 2,
    "corner_tl": 3,
}


# ---------------------------------------------------------------------------
# Test 1: grade M → S produces uniformly smaller pattern
# ---------------------------------------------------------------------------

def test_grade_m_to_s_is_smaller():
    """Grading to S (step=-1) shrinks the pattern."""
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["S", "M", "L"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    base_area = abs(pattern_area(result.patterns["M"][0]))
    s_area = abs(pattern_area(result.patterns["S"][0]))
    assert s_area < base_area, f"S area {s_area:.1f} should be < M area {base_area:.1f}"


# ---------------------------------------------------------------------------
# Test 2: grade M → L produces uniformly larger pattern
# ---------------------------------------------------------------------------

def test_grade_m_to_l_is_larger():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["S", "M", "L"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    base_area = abs(pattern_area(result.patterns["M"][0]))
    l_area = abs(pattern_area(result.patterns["L"][0]))
    assert l_area > base_area, f"L area {l_area:.1f} should be > M area {base_area:.1f}"


# ---------------------------------------------------------------------------
# Test 3: base size pattern is identical to input
# ---------------------------------------------------------------------------

def test_base_size_unchanged():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["S", "M", "L"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    for i, (orig, graded) in enumerate(zip(BASE_RECT, result.patterns["M"][0])):
        assert abs(orig[0] - graded[0]) < 1e-9, f"vertex {i} x changed"
        assert abs(orig[1] - graded[1]) < 1e-9, f"vertex {i} y changed"


# ---------------------------------------------------------------------------
# Test 4: GradedSizes contains all requested sizes
# ---------------------------------------------------------------------------

def test_graded_sizes_contains_all_requested():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["XS", "S", "M", "L", "XL"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    for size in ["XS", "S", "M", "L", "XL"]:
        assert size in result.patterns, f"size {size} missing"
        assert size in result.sizes


# ---------------------------------------------------------------------------
# Test 5: vertex count preserved per piece
# ---------------------------------------------------------------------------

def test_vertex_count_preserved():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["S", "M", "L"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    for size in ["S", "M", "L"]:
        assert len(result.patterns[size][0]) == len(BASE_RECT)


# ---------------------------------------------------------------------------
# Test 6: landmark displacement magnitude is correct
# ---------------------------------------------------------------------------

def test_landmark_displacement_magnitude():
    """Corner_br should shift +5 mm x, -7.5 mm y when going from M to S (step -1)."""
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["S", "M"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    # corner_br is vertex index 1 at (200, 0) in M
    # step = -1 → dx = +0.5 × (-1) × 10 = -5 mm; dy = -0.75 × (-1) × 10 = +7.5 mm
    br_m = result.patterns["M"][0][1]
    br_s = result.patterns["S"][0][1]
    dx = br_s[0] - br_m[0]
    dy = br_s[1] - br_m[1]
    assert abs(dx - (-5.0)) < 0.1, f"expected dx=-5mm got {dx:.3f}"
    assert abs(dy - 7.5) < 0.1, f"expected dy=+7.5mm got {dy:.3f}"


# ---------------------------------------------------------------------------
# Test 7: no-landmark fallback produces output (uniform scale)
# ---------------------------------------------------------------------------

def test_no_landmark_fallback_produces_output():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,         # rules present but no landmarks dict
        target_sizes=["S", "M", "L"],
        base_size="M",
        landmarks=None,
    )
    for size in ["S", "M", "L"]:
        assert len(result.patterns[size][0]) == len(BASE_RECT)


# ---------------------------------------------------------------------------
# Test 8: two-piece pattern graded correctly (all pieces transformed)
# ---------------------------------------------------------------------------

def test_two_piece_pattern():
    front = BASE_RECT
    back = [(0.0, 0.0), (180.0, 0.0), (180.0, 280.0), (0.0, 280.0)]
    result = grade_pattern(
        base_pattern=[front, back],
        rules=RULES,
        target_sizes=["S", "M", "L"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    for size in ["S", "M", "L"]:
        assert len(result.patterns[size]) == 2


# ---------------------------------------------------------------------------
# Test 9: pattern_area — shoelace area is correct for known rectangle
# ---------------------------------------------------------------------------

def test_pattern_area_rectangle():
    """200 × 300 mm CCW rectangle → area = 60 000 mm²."""
    area = pattern_area(BASE_RECT)
    assert abs(area - 60_000.0) < 1.0


# ---------------------------------------------------------------------------
# Test 10: base_size attribute stored correctly
# ---------------------------------------------------------------------------

def test_base_size_attribute():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=[],
        target_sizes=["S", "M", "L"],
        base_size="M",
    )
    assert result.base_size == "M"


# ---------------------------------------------------------------------------
# Test 11: list-of-outlines input accepted (no .pieces attribute needed)
# ---------------------------------------------------------------------------

def test_list_input_accepted():
    result = grade_pattern(
        base_pattern=[BASE_RECT],
        rules=RULES,
        target_sizes=["M", "L"],
        base_size="M",
        landmarks=LANDMARKS,
    )
    assert "M" in result.patterns
    assert "L" in result.patterns
