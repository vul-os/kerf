"""
Tests for kerf_mold.cavity_core_split — cavity/core split and complexity estimation.

Coverage:
  - split_cavity_core on simple block: cavity + core volume ≈ original body volume.
  - Parting surface type is 'planar' for a flat-parting body.
  - Parting surface plane_point pull-axis coordinate ≈ split midpoint.
  - insert_count == 2 for a simple body without undercuts.
  - has_sliders_needed / has_lifters_needed = False for no-undercut body.
  - Undercut body: has_sliders_needed or has_lifters_needed = True.
  - insert_count > 2 for undercut body.
  - estimate_mold_complexity on simple result → score <= 3, tooling = '2-plate'.
  - estimate_mold_complexity on undercut result → lifter/slider recommendation.
  - honest_caveat non-empty string.
  - Empty body (no parting-line segments) returns gracefully.
  - sheet_extension_mm extends parting bbox.
  - parting_surface_complexity == 'planar' for flat parting line.
  - cavity_body volume > 0 for non-degenerate split.
  - core_body volume > 0 for non-degenerate split.
  - estimate_mold_complexity slides_count >= 1 when sliders needed.
  - complexity score clamped to [1, 10].

Wave 10C: parting-line detection + cavity-core split (Cimatron parity)
"""
from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_mold.parting_line import (
    PartingLineDirection,
    PartingLineReport,
    PartingLineSegment,
    detect_parting_line,
)
from kerf_mold.cavity_core_split import (
    split_cavity_core,
    estimate_mold_complexity,
    CavityCoreResult,
    PartingSurface,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_box_body(w=20.0, h=30.0, d=10.0):
    """Box centred at origin; split faces give clear silhouette at z=0."""
    s = math.sin(math.radians(45))
    c = math.cos(math.radians(45))
    hw, hh, hd = w / 2, h / 2, d / 2
    faces = [
        {"id": "F_top",           "normal": [0, 0, 1],   "vertices": [0, 1, 2, 3]},
        {"id": "F_bot",           "normal": [0, 0, -1],  "vertices": [4, 5, 6, 7]},
        {"id": "F_front_top",     "normal": [0, s, c],   "vertices": [0, 1]},
        {"id": "F_front_bot",     "normal": [0, s, -c],  "vertices": [4, 5]},
        {"id": "F_back_top",      "normal": [0, -s, c],  "vertices": [2, 3]},
        {"id": "F_back_bot",      "normal": [0, -s, -c], "vertices": [6, 7]},
        {"id": "F_right_top",     "normal": [s, 0, c],   "vertices": [1, 2]},
        {"id": "F_right_bot",     "normal": [s, 0, -c],  "vertices": [5, 6]},
        {"id": "F_left_top",      "normal": [-s, 0, c],  "vertices": [0, 3]},
        {"id": "F_left_bot",      "normal": [-s, 0, -c], "vertices": [4, 7]},
    ]
    vertices = [
        [-hw, -hh, hd],  # 0
        [ hw, -hh, hd],  # 1
        [ hw,  hh, hd],  # 2
        [-hw,  hh, hd],  # 3
        [-hw, -hh, -hd], # 4
        [ hw, -hh, -hd], # 5
        [ hw,  hh, -hd], # 6
        [-hw,  hh, -hd], # 7
    ]
    edges = [
        {"id": "E_front_mid", "face_ids": ["F_front_top", "F_front_bot"],
         "p_start": [-hw, hh, 0], "p_end": [hw, hh, 0]},
        {"id": "E_back_mid",  "face_ids": ["F_back_top",  "F_back_bot"],
         "p_start": [-hw, -hh, 0], "p_end": [hw, -hh, 0]},
        {"id": "E_right_mid", "face_ids": ["F_right_top", "F_right_bot"],
         "p_start": [hw, -hh, 0], "p_end": [hw,  hh, 0]},
        {"id": "E_left_mid",  "face_ids": ["F_left_top",  "F_left_bot"],
         "p_start": [-hw,  hh, 0], "p_end": [-hw, -hh, 0]},
    ]
    return {"faces": faces, "edges": edges, "vertices": vertices}


def _undercut_body():
    """Body with undercut edges."""
    faces = [
        {"id": "F_top",   "normal": [0, 0, 1],    "vertices": [0, 1, 2, 3]},
        {"id": "F_under", "normal": [0, -1, -0.5], "vertices": [4, 5]},
        {"id": "F_under2","normal": [0,  1, -0.5], "vertices": [6, 7]},
        {"id": "F_sil_a", "normal": [0, 0.7, 0.5], "vertices": [0, 1]},
        {"id": "F_sil_b", "normal": [0, 0.7, -0.5],"vertices": [4, 5]},
    ]
    vertices = [
        [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10],
        [0, 0, -5], [10, 0, -5], [10, 10, -5], [0, 10, -5],
    ]
    edges = [
        # Undercut: both N·z < 0
        {"id": "E_undercut", "face_ids": ["F_under", "F_under2"],
         "p_start": [5, 0, -5], "p_end": [5, 10, -5]},
        # Silhouette: sign change
        {"id": "E_silhouette", "face_ids": ["F_sil_a", "F_sil_b"],
         "p_start": [0, 5, 0], "p_end": [10, 5, 0]},
    ]
    return {"faces": faces, "edges": edges, "vertices": vertices}


def _detect(body, pull=None):
    pull = pull or [0, 0, 1]
    direction = PartingLineDirection(pull_direction=np.array(pull, dtype=float))
    return detect_parting_line(body, direction)


def _split(body, pl_report, pull=None, sheet_ext=50.0):
    pull = np.array(pull or [0, 0, 1], dtype=float)
    return split_cavity_core(body, pl_report, pull, sheet_extension_mm=sheet_ext)


# ---------------------------------------------------------------------------
# Tests — split_cavity_core
# ---------------------------------------------------------------------------

class TestSimpleBoxSplit:
    def setup_method(self):
        self.body = _simple_box_body(w=20.0, h=30.0, d=10.0)
        self.pl = _detect(self.body)
        self.result = _split(self.body, self.pl)

    def test_returns_result_type(self):
        assert isinstance(self.result, CavityCoreResult)

    def test_parting_surface_is_planar(self):
        assert self.result.parting_surface.surface_type == "planar"

    def test_parting_surface_complexity_planar(self):
        assert self.result.parting_surface_complexity == "planar"

    def test_split_plane_at_z_zero(self):
        """For a box with silhouette edges at z=0, split plane should be near z=0."""
        z = float(self.result.parting_surface.plane_point[2])
        assert abs(z) < 1e-6, f"Expected split at z=0, got z={z}"

    def test_cavity_volume_positive(self):
        assert self.result.cavity_body["volume_mm3"] > 0.0

    def test_core_volume_positive(self):
        assert self.result.core_body["volume_mm3"] > 0.0

    def test_cavity_plus_core_approx_original(self):
        """Cavity + core volumes should approximately equal original body bbox volume."""
        total = (
            self.result.cavity_body["volume_mm3"]
            + self.result.core_body["volume_mm3"]
        )
        # Body bbox: 20×30×10 = 6000
        # Split at z=0 (midpoint): each half = 3000
        # Total = 6000
        assert abs(total - 6000.0) < 1.0, f"Combined volume = {total}, expected ≈ 6000"

    def test_insert_count_two(self):
        assert self.result.insert_count == 2

    def test_no_sliders_needed(self):
        assert self.result.has_sliders_needed is False

    def test_no_lifters_needed(self):
        assert self.result.has_lifters_needed is False

    def test_honest_caveat_non_empty(self):
        assert len(self.result.honest_caveat) > 20

    def test_cavity_and_core_body_dicts(self):
        assert isinstance(self.result.cavity_body, dict)
        assert isinstance(self.result.core_body, dict)
        assert "volume_mm3" in self.result.cavity_body
        assert "volume_mm3" in self.result.core_body

    def test_parting_surface_plane_normal_z(self):
        """Plane normal should be close to [0,0,1] for Z-pull."""
        np.testing.assert_allclose(
            self.result.parting_surface.plane_normal, [0, 0, 1], atol=1e-6
        )


class TestSheetExtension:
    """Parting sheet extended beyond body bbox by sheet_extension_mm."""

    def test_extended_bbox_wider(self):
        body = _simple_box_body(w=20.0, h=30.0, d=10.0)
        pl = _detect(body)
        result_std = _split(body, pl, sheet_ext=0.0)
        result_ext = _split(body, pl, sheet_ext=50.0)
        # Extended bbox should be larger in X and Y (perp to Z pull)
        std_bbox = result_std.parting_surface.bbox_extended
        ext_bbox = result_ext.parting_surface.bbox_extended
        assert ext_bbox[0] < std_bbox[0], "X min should be smaller with extension"
        assert ext_bbox[3] > std_bbox[3], "X max should be larger with extension"
        assert ext_bbox[1] < std_bbox[1], "Y min should be smaller with extension"
        assert ext_bbox[4] > std_bbox[4], "Y max should be larger with extension"


class TestUndercutBodySplit:
    """Body with undercuts should report side-action requirements."""

    def setup_method(self):
        self.body = _undercut_body()
        self.pl = _detect(self.body)
        self.result = _split(self.body, self.pl)

    def test_has_undercuts_in_pl(self):
        assert self.pl.has_undercuts is True

    def test_insert_count_greater_than_two(self):
        assert self.result.insert_count > 2

    def test_sliders_or_lifters_needed(self):
        assert self.result.has_sliders_needed or self.result.has_lifters_needed


class TestEmptyBody:
    """Empty body (no edges) → graceful empty result."""

    def test_empty_body_no_crash(self):
        body = {"faces": [], "edges": [], "vertices": []}
        pl = _detect(body)
        result = _split(body, pl)
        assert isinstance(result, CavityCoreResult)
        assert result.cavity_body["volume_mm3"] == 0.0
        assert result.core_body["volume_mm3"] == 0.0


# ---------------------------------------------------------------------------
# Tests — estimate_mold_complexity
# ---------------------------------------------------------------------------

class TestEstimateMoldComplexity:
    def _make_result(self, has_sliders=False, has_lifters=False,
                     insert_count=2, complexity="planar"):
        ps = PartingSurface(
            surface_type=complexity,
            plane_point=np.zeros(3),
            plane_normal=np.array([0.0, 0.0, 1.0]),
            bbox_extended=[0.0] * 6,
        )
        return CavityCoreResult(
            parting_surface=ps,
            cavity_body={"volume_mm3": 1000.0},
            core_body={"volume_mm3": 1000.0},
            insert_count=insert_count,
            parting_surface_complexity=complexity,
            has_lifters_needed=has_lifters,
            has_sliders_needed=has_sliders,
            honest_caveat="test",
        )

    def test_simple_two_plate(self):
        result = self._make_result()
        comp = estimate_mold_complexity(result)
        assert comp["complexity_score"] <= 3
        assert comp["recommended_tooling"] == "2-plate"

    def test_undercut_lifter_increases_score(self):
        result = self._make_result(has_lifters=True)
        comp = estimate_mold_complexity(result)
        assert comp["complexity_score"] > 1
        assert "lifter" in comp["notes"].lower()

    def test_slider_increases_score(self):
        result = self._make_result(has_sliders=True)
        comp = estimate_mold_complexity(result)
        assert comp["complexity_score"] >= 3

    def test_slides_count_positive_when_needed(self):
        result = self._make_result(has_sliders=True, has_lifters=True)
        comp = estimate_mold_complexity(result)
        assert comp["slides_count"] >= 1

    def test_hot_runner_for_complex(self):
        result = self._make_result(
            has_sliders=True, has_lifters=True, insert_count=6,
            complexity="free_form"
        )
        comp = estimate_mold_complexity(result)
        assert comp["recommended_tooling"] == "hot_runner"

    def test_score_clamped_max_10(self):
        result = self._make_result(
            has_sliders=True, has_lifters=True, insert_count=10,
            complexity="free_form"
        )
        comp = estimate_mold_complexity(result)
        assert comp["complexity_score"] <= 10

    def test_score_clamped_min_1(self):
        result = self._make_result()
        comp = estimate_mold_complexity(result)
        assert comp["complexity_score"] >= 1

    def test_honest_caveat_non_empty(self):
        result = self._make_result()
        comp = estimate_mold_complexity(result)
        assert len(comp["honest_caveat"]) > 20

    def test_returns_dict_with_required_keys(self):
        result = self._make_result()
        comp = estimate_mold_complexity(result)
        for key in ("complexity_score", "recommended_tooling", "slides_count",
                    "notes", "honest_caveat"):
            assert key in comp, f"Missing key: {key}"
