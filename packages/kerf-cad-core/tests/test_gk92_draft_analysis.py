"""GK-92: Draft analysis overlay — hermetic pytest oracle.

Oracles
-------
1. Cylinder pulled along its axis (Z):
   - Side face (CylinderSurface): normal ⊥ axis  → draft = 0° (vertical)
   - Top cap (Plane, normal = +Z):               → draft = +90° (positive)
   - Bottom cap (Plane, normal = −Z):            → draft = −90° (negative)

2. Box pulled along Z:
   - Top face (normal = +Z):    → draft = +90°  (positive)
   - Bottom face (normal = −Z): → draft = −90°  (negative)
   - 4 side faces (normal ⊥ Z): → draft = 0°    (vertical)

Both oracles use default thresholds (±3°).
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.geom.brep import make_cylinder, make_box
from kerf_cad_core.geom.surface_analysis import draft_analysis
from kerf_cad_core import geom as _geom_pkg  # public façade


# ---------------------------------------------------------------------------
# Public export check
# ---------------------------------------------------------------------------

class TestPublicExport:
    def test_draft_analysis_importable_from_geom(self):
        """draft_analysis must be exported from kerf_cad_core.geom."""
        assert hasattr(_geom_pkg, "draft_analysis")
        assert _geom_pkg.draft_analysis is draft_analysis


# ---------------------------------------------------------------------------
# Cylinder oracle
# ---------------------------------------------------------------------------

class TestDraftAnalysisCylinder:
    """Cylinder pulled along its own axis.

    make_cylinder produces 3 faces:
      - side_face  : CylinderSurface — normals radial (⊥ axis)  → 0°
      - bottom_face: Plane at z=0    — normal = -Z               → −90°
      - top_face   : Plane at z=h    — normal = +Z               → +90°
    """

    @pytest.fixture
    def cylinder_result(self):
        body = make_cylinder(
            center=(0.0, 0.0, 0.0),
            axis=(0.0, 0.0, 1.0),
            radius=1.0,
            height=2.0,
        )
        return draft_analysis(body, pull_direction=(0.0, 0.0, 1.0))

    def test_ok(self, cylinder_result):
        assert cylinder_result["ok"] is True, cylinder_result.get("reason")

    def test_three_faces(self, cylinder_result):
        assert len(cylinder_result["per_face_angles"]) == 3

    def test_side_face_is_vertical(self, cylinder_result):
        """Side face normal ⊥ axis → draft ≈ 0° → classified vertical."""
        assert len(cylinder_result["vertical_faces"]) == 1
        fid = cylinder_result["vertical_faces"][0]
        angle = cylinder_result["per_face_angles"][fid]
        assert abs(angle) < 1.0, (
            f"Side face draft angle {angle:.3f}° should be ~0°"
        )

    def test_top_cap_positive_90(self, cylinder_result):
        """Top cap normal = +Z → draft = +90°."""
        positive = cylinder_result["positive_faces"]
        assert len(positive) == 1
        fid = positive[0]
        angle = cylinder_result["per_face_angles"][fid]
        assert abs(angle - 90.0) < 1.0, (
            f"Top cap draft angle {angle:.3f}° should be ~+90°"
        )

    def test_bottom_cap_negative_90(self, cylinder_result):
        """Bottom cap normal = −Z → draft = −90°."""
        negative = cylinder_result["negative_faces"]
        assert len(negative) == 1
        fid = negative[0]
        angle = cylinder_result["per_face_angles"][fid]
        assert abs(angle + 90.0) < 1.0, (
            f"Bottom cap draft angle {angle:.3f}° should be ~−90°"
        )

    def test_colours_correct(self, cylinder_result):
        """Side = yellow, top = green, bottom = red."""
        colours = cylinder_result["face_colours"]
        for fid in cylinder_result["vertical_faces"]:
            assert colours[fid] == (1.0, 1.0, 0.0), "vertical should be yellow"
        for fid in cylinder_result["positive_faces"]:
            assert colours[fid] == (0.0, 1.0, 0.0), "positive should be green"
        for fid in cylinder_result["negative_faces"]:
            assert colours[fid] == (1.0, 0.0, 0.0), "negative should be red"


# ---------------------------------------------------------------------------
# Box oracle
# ---------------------------------------------------------------------------

class TestDraftAnalysisBox:
    """Box pulled along Z.

    make_box produces 6 faces:
      - top face   (normal = +Z):  → +90° (positive)
      - bottom face (normal = −Z): → −90° (negative)
      - 4 side faces (normals ⊥ Z): → 0° (vertical)
    """

    @pytest.fixture
    def box_result(self):
        body = make_box(origin=(0.0, 0.0, 0.0), size=(2.0, 2.0, 2.0))
        return draft_analysis(body, pull_direction=(0.0, 0.0, 1.0))

    def test_ok(self, box_result):
        assert box_result["ok"] is True, box_result.get("reason")

    def test_six_faces(self, box_result):
        assert len(box_result["per_face_angles"]) == 6

    def test_one_positive_face(self, box_result):
        """Top face: +90°."""
        assert len(box_result["positive_faces"]) == 1
        fid = box_result["positive_faces"][0]
        angle = box_result["per_face_angles"][fid]
        assert abs(angle - 90.0) < 1.0, (
            f"Top face draft {angle:.3f}° should be ~+90°"
        )

    def test_one_negative_face(self, box_result):
        """Bottom face: −90°."""
        assert len(box_result["negative_faces"]) == 1
        fid = box_result["negative_faces"][0]
        angle = box_result["per_face_angles"][fid]
        assert abs(angle + 90.0) < 1.0, (
            f"Bottom face draft {angle:.3f}° should be ~−90°"
        )

    def test_four_vertical_faces(self, box_result):
        """Four side faces: ~0°."""
        assert len(box_result["vertical_faces"]) == 4
        for fid in box_result["vertical_faces"]:
            angle = box_result["per_face_angles"][fid]
            assert abs(angle) < 1.0, (
                f"Side face draft {angle:.3f}° should be ~0°"
            )


# ---------------------------------------------------------------------------
# Error / edge cases
# ---------------------------------------------------------------------------

class TestDraftAnalysisEdgeCases:
    def test_zero_pull_direction_returns_error(self):
        body = make_box()
        result = draft_analysis(body, pull_direction=(0.0, 0.0, 0.0))
        assert result["ok"] is False
        assert "zero" in result["reason"].lower()

    def test_inverted_pull_direction_swaps_positive_negative(self):
        """Pulling −Z instead of +Z should swap positive / negative labels."""
        body = make_box()
        r_pos = draft_analysis(body, pull_direction=(0.0, 0.0, 1.0))
        r_neg = draft_analysis(body, pull_direction=(0.0, 0.0, -1.0))

        # Faces that were positive in +Z should be negative in −Z and vice versa.
        assert set(r_pos["positive_faces"]) == set(r_neg["negative_faces"])
        assert set(r_pos["negative_faces"]) == set(r_neg["positive_faces"])
        assert set(r_pos["vertical_faces"]) == set(r_neg["vertical_faces"])

    def test_custom_thresholds_narrow(self):
        """With very narrow threshold (0.1°), nearly all faces might be neutral."""
        body = make_box()
        result = draft_analysis(
            body,
            pull_direction=(0.0, 0.0, 1.0),
            positive_threshold_deg=89.0,
            negative_threshold_deg=-89.0,
        )
        assert result["ok"] is True
        # With threshold at 89°, side faces (0°) and most others land in vertical
        assert len(result["vertical_faces"]) >= 4

    def test_invalid_thresholds(self):
        """negative_threshold >= positive_threshold should return error."""
        body = make_box()
        result = draft_analysis(
            body,
            pull_direction=(0.0, 0.0, 1.0),
            positive_threshold_deg=3.0,
            negative_threshold_deg=5.0,  # invalid: neg > pos
        )
        assert result["ok"] is False

    def test_non_unit_pull_direction_same_result(self):
        """Scaling pull_direction should not change angles."""
        body = make_cylinder(axis=(0, 0, 1), radius=1.0, height=1.0)
        r1 = draft_analysis(body, pull_direction=(0.0, 0.0, 1.0))
        r2 = draft_analysis(body, pull_direction=(0.0, 0.0, 5.0))
        for fid in r1["per_face_angles"]:
            assert abs(r1["per_face_angles"][fid] - r2["per_face_angles"][fid]) < 1e-9
