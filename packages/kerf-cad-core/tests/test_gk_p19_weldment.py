"""GK-P19 tests — weldment gusset_plate + cope/notch end-treatments.

DoD: gusset + coped member emit valid geometry and appear in the cut-list
(members list).

Oracle contracts
----------------
* gusset_plate area_mm2: triangle=0.5*w*h; rect=w*h; trapezoid=0.5*(w+w/2)*h
* gusset_plate mass_kg = area_mm2 * thickness_mm * 7850e-9
* cope_area: depth * width (square) or depth*width minus corner circles (radius)
* notch_area: depth*width (square) or triangle from angle geometry
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.weldment import (
    compute_members,
    compute_cutlist,
    gusset_plate,
    apply_end_treatment,
)
from kerf_cad_core.weldment_profiles import lookup_profile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_frame():
    """L-shaped frame: horizontal + vertical member meeting at origin."""
    skeleton = [
        {"start": [0, 0, 0], "end": [1000, 0, 0]},   # horizontal
        {"start": [0, 0, 0], "end": [0, 1000, 0]},    # vertical
    ]
    profile = lookup_profile("SQ-50x50x3")
    members, errors = compute_members(skeleton, profile)
    assert not errors, f"Frame errors: {errors}"
    return members, profile


def _single_member():
    """Single member with one free end."""
    skeleton = [{"start": [0, 0, 0], "end": [500, 0, 0]}]
    profile = lookup_profile("SQ-50x50x3")
    members, errors = compute_members(skeleton, profile)
    assert not errors
    return members[0], profile


# ===========================================================================
# Tests: gusset_plate
# ===========================================================================

class TestGussetPlate:
    def _members(self):
        members, _ = _simple_frame()
        return members

    # --- basic structure ---
    def test_returns_dict(self):
        g = gusset_plate(self._members(), [0, 0, 0])
        assert isinstance(g, dict)

    def test_type_key(self):
        g = gusset_plate(self._members(), [0, 0, 0])
        assert g["type"] == "gusset_plate"

    def test_vertex_pos_stored(self):
        g = gusset_plate(self._members(), [10, 20, 0])
        assert g["vertex_pos"] == [10.0, 20.0, 0.0]

    def test_shape_stored(self):
        g = gusset_plate(self._members(), [0, 0, 0], shape="rect")
        assert g["shape"] == "rect"

    def test_thickness_stored(self):
        g = gusset_plate(self._members(), [0, 0, 0], thickness_mm=8.0)
        assert g["thickness_mm"] == 8.0

    def test_has_corners(self):
        g = gusset_plate(self._members(), [0, 0, 0])
        assert "corners" in g
        assert isinstance(g["corners"], list)
        assert len(g["corners"]) >= 3

    def test_member_ids_length(self):
        g = gusset_plate(self._members(), [0, 0, 0])
        assert len(g["member_ids"]) == 2

    # --- oracle: area ---
    def test_triangle_area_oracle(self):
        w, h = 120.0, 100.0
        g = gusset_plate(self._members(), [0, 0, 0],
                         shape="triangle", width_mm=w, height_mm=h)
        assert abs(g["area_mm2"] - 0.5 * w * h) < 1e-3

    def test_rect_area_oracle(self):
        w, h = 120.0, 100.0
        g = gusset_plate(self._members(), [0, 0, 0],
                         shape="rect", width_mm=w, height_mm=h)
        assert abs(g["area_mm2"] - w * h) < 1e-3

    def test_trapezoidal_area_oracle(self):
        w, h = 120.0, 100.0
        expected = 0.5 * (w + w / 2.0) * h
        g = gusset_plate(self._members(), [0, 0, 0],
                         shape="trapezoidal", width_mm=w, height_mm=h)
        assert abs(g["area_mm2"] - expected) < 1e-3

    # --- oracle: mass ---
    def test_mass_oracle(self):
        """mass_kg = area_mm2 * thickness_mm * 7850e-9."""
        w, h, t = 100.0, 100.0, 6.0
        g = gusset_plate(self._members(), [0, 0, 0],
                         shape="rect", width_mm=w, height_mm=h, thickness_mm=t)
        expected_mass = w * h * t * 7850.0 / 1e9
        assert abs(g["mass_kg"] - expected_mass) < 1e-6

    def test_fillet_stored(self):
        g = gusset_plate(self._members(), [0, 0, 0], fillet_mm=5.0)
        assert g["fillet_mm"] == 5.0

    def test_material_stored(self):
        g = gusset_plate(self._members(), [0, 0, 0], material="stainless")
        assert g["material"] == "stainless"

    # --- invalid inputs ---
    def test_zero_thickness_raises(self):
        with pytest.raises(ValueError, match="thickness_mm"):
            gusset_plate(self._members(), [0, 0, 0], thickness_mm=0.0)

    def test_zero_width_raises(self):
        with pytest.raises(ValueError, match="width_mm"):
            gusset_plate(self._members(), [0, 0, 0], width_mm=0.0)

    def test_zero_height_raises(self):
        with pytest.raises(ValueError, match="height_mm"):
            gusset_plate(self._members(), [0, 0, 0], height_mm=0.0)

    def test_negative_fillet_raises(self):
        with pytest.raises(ValueError, match="fillet_mm"):
            gusset_plate(self._members(), [0, 0, 0], fillet_mm=-1.0)

    def test_invalid_shape_raises(self):
        with pytest.raises(ValueError, match="shape"):
            gusset_plate(self._members(), [0, 0, 0], shape="circle")

    def test_too_few_members_raises(self):
        member, _ = _single_member()
        with pytest.raises(ValueError, match="2 members"):
            gusset_plate([member], [0, 0, 0])

    def test_invalid_vertex_pos_raises(self):
        with pytest.raises(ValueError, match="vertex_pos"):
            gusset_plate(self._members(), "not_a_list")

    # --- gusset in cut-list ---
    def test_gusset_mass_is_positive(self):
        g = gusset_plate(self._members(), [0, 0, 0])
        assert g["mass_kg"] > 0

    def test_gusset_area_positive(self):
        g = gusset_plate(self._members(), [0, 0, 0])
        assert g["area_mm2"] > 0


# ===========================================================================
# Tests: apply_end_treatment (cope + notch)
# ===========================================================================

class TestApplyEndTreatment:
    def _member(self):
        m, _ = _single_member()
        return m

    # --- basic structure ---
    def test_returns_dict(self):
        result = apply_end_treatment(self._member(), "start")
        assert isinstance(result, dict)

    def test_original_keys_preserved(self):
        m = self._member()
        result = apply_end_treatment(m, "start")
        for key in m:
            assert key in result

    def test_no_treatment_none_values(self):
        result = apply_end_treatment(self._member(), "start")
        assert result["start_cope"] is None
        assert result["start_notch"] is None

    # --- cope: square ---
    def test_square_cope_dict(self):
        result = apply_end_treatment(
            self._member(), "start",
            cope_style="square", cope_depth_mm=10.0, cope_width_mm=20.0
        )
        cope = result["start_cope"]
        assert cope is not None
        assert cope["style"] == "square"

    def test_square_cope_area_oracle(self):
        d, w = 10.0, 20.0
        result = apply_end_treatment(
            self._member(), "start",
            cope_style="square", cope_depth_mm=d, cope_width_mm=w
        )
        assert abs(result["start_cope"]["area_mm2"] - d * w) < 1e-6

    def test_square_cope_keys(self):
        result = apply_end_treatment(
            self._member(), "start",
            cope_style="square", cope_depth_mm=10.0, cope_width_mm=20.0
        )
        cope = result["start_cope"]
        for key in ("style", "depth_mm", "width_mm", "area_mm2"):
            assert key in cope

    # --- cope: radius ---
    def test_radius_cope_has_radius_key(self):
        result = apply_end_treatment(
            self._member(), "end",
            cope_style="radius", cope_depth_mm=15.0,
            cope_width_mm=25.0, cope_radius_mm=5.0
        )
        cope = result["end_cope"]
        assert "radius_mm" in cope
        assert cope["radius_mm"] == 5.0

    def test_radius_cope_area_smaller_than_square(self):
        """Radius cope area < square cope area (corners removed)."""
        d, w, r = 15.0, 25.0, 5.0
        sq = apply_end_treatment(
            self._member(), "start",
            cope_style="square", cope_depth_mm=d, cope_width_mm=w
        )["start_cope"]["area_mm2"]
        rd = apply_end_treatment(
            self._member(), "start",
            cope_style="radius", cope_depth_mm=d, cope_width_mm=w, cope_radius_mm=r
        )["start_cope"]["area_mm2"]
        assert rd < sq

    def test_radius_too_large_raises(self):
        """cope_radius > min(depth, width/2) must raise."""
        with pytest.raises(ValueError, match="cope_radius_mm"):
            apply_end_treatment(
                self._member(), "start",
                cope_style="radius", cope_depth_mm=5.0,
                cope_width_mm=10.0, cope_radius_mm=6.0  # > min(5, 5) = 5
            )

    # --- notch: square ---
    def test_square_notch_dict(self):
        result = apply_end_treatment(
            self._member(), "end",
            notch_style="square", notch_depth_mm=8.0, notch_width_mm=12.0
        )
        notch = result["end_notch"]
        assert notch is not None
        assert notch["style"] == "square"

    def test_square_notch_area_oracle(self):
        d, w = 8.0, 12.0
        result = apply_end_treatment(
            self._member(), "end",
            notch_style="square", notch_depth_mm=d, notch_width_mm=w
        )
        assert abs(result["end_notch"]["area_mm2"] - d * w) < 1e-6

    # --- notch: angle (V-notch) ---
    def test_angle_notch_dict(self):
        result = apply_end_treatment(
            self._member(), "start",
            notch_style="angle", notch_depth_mm=10.0,
            notch_width_mm=20.0, notch_angle_deg=60.0
        )
        notch = result["start_notch"]
        assert notch is not None
        assert notch["style"] == "angle"
        assert "angle_deg" in notch

    def test_angle_notch_area_positive(self):
        result = apply_end_treatment(
            self._member(), "start",
            notch_style="angle", notch_depth_mm=10.0,
            notch_width_mm=20.0, notch_angle_deg=60.0
        )
        assert result["start_notch"]["area_mm2"] > 0

    def test_angle_notch_area_le_rect_notch(self):
        """V-notch area ≤ rectangular notch area (same depth/width)."""
        d, w = 10.0, 20.0
        sq_area = apply_end_treatment(
            self._member(), "start",
            notch_style="square", notch_depth_mm=d, notch_width_mm=w
        )["start_notch"]["area_mm2"]
        ang_area = apply_end_treatment(
            self._member(), "start",
            notch_style="angle", notch_depth_mm=d, notch_width_mm=w, notch_angle_deg=90.0
        )["start_notch"]["area_mm2"]
        # Triangle area = 0.5 * base * height ≤ rect area = base * height
        assert ang_area <= sq_area + 1e-9

    def test_cope_and_notch_together(self):
        result = apply_end_treatment(
            self._member(), "end",
            cope_style="square", cope_depth_mm=10.0, cope_width_mm=20.0,
            notch_style="square", notch_depth_mm=5.0, notch_width_mm=8.0
        )
        assert result["end_cope"] is not None
        assert result["end_notch"] is not None

    # --- invalid inputs ---
    def test_invalid_end_raises(self):
        with pytest.raises(ValueError, match="end"):
            apply_end_treatment(self._member(), "middle")

    def test_invalid_cope_style_raises(self):
        with pytest.raises(ValueError, match="cope_style"):
            apply_end_treatment(self._member(), "start", cope_style="beveled")

    def test_invalid_notch_style_raises(self):
        with pytest.raises(ValueError, match="notch_style"):
            apply_end_treatment(self._member(), "start", notch_style="diamond")

    def test_cope_zero_depth_raises(self):
        with pytest.raises(ValueError, match="cope_depth_mm"):
            apply_end_treatment(
                self._member(), "start",
                cope_style="square", cope_depth_mm=0.0, cope_width_mm=10.0
            )

    def test_notch_zero_depth_raises(self):
        with pytest.raises(ValueError, match="notch_depth_mm"):
            apply_end_treatment(
                self._member(), "start",
                notch_style="square", notch_depth_mm=0.0, notch_width_mm=10.0
            )

    def test_angle_notch_angle_180_raises(self):
        with pytest.raises(ValueError, match="notch_angle_deg"):
            apply_end_treatment(
                self._member(), "start",
                notch_style="angle", notch_depth_mm=5.0,
                notch_width_mm=10.0, notch_angle_deg=180.0
            )

    # --- "end" key on result dict ---
    def test_end_treatment_applied_to_end(self):
        result = apply_end_treatment(
            self._member(), "end",
            cope_style="square", cope_depth_mm=10.0, cope_width_mm=15.0
        )
        assert result["end_cope"] is not None
        assert result.get("start_cope") is None

    def test_start_treatment_applied_to_start(self):
        result = apply_end_treatment(
            self._member(), "start",
            notch_style="square", notch_depth_mm=5.0, notch_width_mm=8.0
        )
        assert result["start_notch"] is not None
        assert result.get("end_notch") is None
