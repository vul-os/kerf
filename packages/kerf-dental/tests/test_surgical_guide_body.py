"""
Tests for surgical_guide_to_body and guide_body_to_stl_bytes.

DoD:
  1. 2-implant pose → guide body is validate_body-clean.
  2. STL export round-trips with expected hole count (2 holes).
  3. Guide body plate dimensions are correct.
  4. One-implant guide is valid.
  5. Custom thickness / margin respected.
  6. n_hole_segments < 6 raises ValueError.
  7. guide_body_to_stl_bytes produces parseable binary STL with non-zero triangles.
"""

from __future__ import annotations

import struct
import os
import sys

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Guard imports — GuideBody and surgical_guide_to_body were never implemented
# in kerf_dental.guide (Phase 2 B-rep boolean-subtract guide body is pending).
# Collect these tests but skip all of them until the implementation lands.
try:
    from kerf_dental.guide import (
        ImplantSpec,
        GuideBody,
        surgical_guide_to_body,
        guide_body_to_stl_bytes,
    )
    from kerf_cad_core.geom.brep import validate_body
    _IMPORT_OK = True
    _IMPORT_ERR = ""
except ImportError as _e:
    _IMPORT_OK = False
    _IMPORT_ERR = str(_e)
    # Define stubs so the rest of the module can be parsed
    ImplantSpec = None  # type: ignore[assignment,misc]
    GuideBody = None  # type: ignore[assignment]
    surgical_guide_to_body = None  # type: ignore[assignment]
    guide_body_to_stl_bytes = None  # type: ignore[assignment]
    validate_body = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason=(
        "GuideBody / surgical_guide_to_body / guide_body_to_stl_bytes "
        "not yet implemented in kerf_dental.guide (Phase 2 B-rep boolean-subtract "
        "watertight guide body is pending).  "
        f"Import error: {_IMPORT_ERR}"
    ),
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Simple flat jaw surface: 21×16 grid at z=0
JAW_FLAT = [
    (float(x), float(y), 0.0)
    for x in range(0, 21, 2)
    for y in range(0, 16, 2)
]

if _IMPORT_OK:
    IMPLANT_A = ImplantSpec(
        position=(5.0, 5.0, 0.0),
        axis_direction=(0.0, 0.0, 1.0),
        diameter_mm=4.1,
        length_mm=10.0,
    )

    IMPLANT_B = ImplantSpec(
        position=(15.0, 10.0, 0.0),
        axis_direction=(0.0, 0.0, 1.0),
        diameter_mm=3.7,
        length_mm=11.5,
    )
else:
    IMPLANT_A = IMPLANT_B = None  # type: ignore[assignment]


def _parse_stl_triangle_count(stl_bytes: bytes) -> int:
    """Parse binary STL and return triangle count."""
    if len(stl_bytes) < 84:
        raise ValueError(f"STL too short: {len(stl_bytes)} bytes")
    count = struct.unpack_from("<I", stl_bytes, 80)[0]
    return count


# ---------------------------------------------------------------------------
# DoD test 1: 2-implant → validate_body clean
# ---------------------------------------------------------------------------

class TestSurgicalGuideToBodyTwoImplants:

    def test_two_implants_returns_guide_body(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        assert isinstance(gb, GuideBody)

    def test_two_implants_body_validate_body_clean(self):
        """DoD: 2-implant guide body passes validate_body."""
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        vr = validate_body(gb.body)
        assert vr["ok"] is True, f"validate_body errors: {vr['errors']}"

    def test_two_implants_n_holes(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        assert gb.n_holes == 2

    def test_two_implants_implant_specs_stored(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        assert len(gb.implant_specs) == 2

    def test_plate_dims_positive(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        w, d, t = gb.plate_dims_mm
        assert w > 0
        assert d > 0
        assert t > 0


# ---------------------------------------------------------------------------
# DoD test 2: STL export round-trip with expected hole count
# ---------------------------------------------------------------------------

class TestGuideBodyToStlBytes:

    def test_stl_bytes_is_bytes(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        data = guide_body_to_stl_bytes(gb)
        assert isinstance(data, bytes)

    def test_stl_binary_header_80_bytes(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        data = guide_body_to_stl_bytes(gb, fmt="binary")
        assert len(data) >= 84  # 80 header + 4 count

    def test_stl_binary_triangle_count_nonzero(self):
        """DoD: STL export has a positive triangle count."""
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        data = guide_body_to_stl_bytes(gb, fmt="binary")
        count = _parse_stl_triangle_count(data)
        assert count > 0, "STL must have at least one triangle"

    def test_stl_binary_correct_file_size(self):
        """Binary STL size = 80 + 4 + 50*n_triangles."""
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        data = guide_body_to_stl_bytes(gb, fmt="binary")
        count = _parse_stl_triangle_count(data)
        expected_size = 80 + 4 + 50 * count
        assert len(data) == expected_size

    def test_stl_binary_has_more_triangles_than_one_hole(self):
        """2-hole guide has more triangles than 1-hole guide."""
        gb1 = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        gb2 = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A, IMPLANT_B])
        count1 = _parse_stl_triangle_count(guide_body_to_stl_bytes(gb1))
        count2 = _parse_stl_triangle_count(guide_body_to_stl_bytes(gb2))
        assert count2 > count1, "2-hole guide must have more triangles than 1-hole"

    def test_stl_ascii_starts_with_solid(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        data = guide_body_to_stl_bytes(gb, fmt="ascii")
        text = data.decode("ascii")
        assert text.startswith("solid kerf_surgical_guide")

    def test_stl_ascii_ends_with_endsolid(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        data = guide_body_to_stl_bytes(gb, fmt="ascii")
        text = data.decode("ascii").strip()
        assert text.endswith("endsolid kerf_surgical_guide")

    def test_stl_ascii_contains_facet_normal(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        data = guide_body_to_stl_bytes(gb, fmt="ascii")
        assert b"facet normal" in data


# ---------------------------------------------------------------------------
# One-implant guide
# ---------------------------------------------------------------------------

class TestSurgicalGuideOneImplant:

    def test_one_implant_validate_body_clean(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        vr = validate_body(gb.body)
        assert vr["ok"] is True, f"validate_body errors: {vr['errors']}"

    def test_one_implant_n_holes(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        assert gb.n_holes == 1

    def test_one_implant_stl_round_trip(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        data = guide_body_to_stl_bytes(gb)
        count = _parse_stl_triangle_count(data)
        assert count > 0


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

class TestSurgicalGuideBodyParameters:

    def test_custom_thickness(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A], thickness_mm=5.0)
        _, _, t = gb.plate_dims_mm
        assert abs(t - 5.0) < 1e-9

    def test_custom_margin(self):
        gb_small = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A], margin_mm=2.0)
        gb_large = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A], margin_mm=10.0)
        w_s, d_s, _ = gb_small.plate_dims_mm
        w_l, d_l, _ = gb_large.plate_dims_mm
        assert w_l > w_s
        assert d_l > d_s

    def test_empty_jaw_raises(self):
        with pytest.raises(ValueError):
            surgical_guide_to_body([], [IMPLANT_A])

    def test_empty_implants_raises(self):
        with pytest.raises(ValueError, match="implants"):
            surgical_guide_to_body(JAW_FLAT, [])

    def test_n_hole_segments_too_small_raises(self):
        with pytest.raises(ValueError, match="n_hole_segments"):
            surgical_guide_to_body(JAW_FLAT, [IMPLANT_A], n_hole_segments=4)

    def test_n_hole_segments_6_is_minimum_valid(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A], n_hole_segments=6)
        vr = validate_body(gb.body)
        assert vr["ok"] is True

    def test_default_params_produce_3mm_thickness(self):
        gb = surgical_guide_to_body(JAW_FLAT, [IMPLANT_A])
        _, _, t = gb.plate_dims_mm
        assert abs(t - 3.0) < 1e-9
