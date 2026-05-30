"""
Tests for kerf_cad_core.geom.section_cutaway
=============================================

Analytical oracle tests per DoD:
1. Cube section by midplane        — 10×10×10 cube cut at z=5
2. Cylinder section by midplane    — unit cylinder height 2 cut at y=0
3. Hatch density oracle            — 10×10 square, spacing=2.0, 45° → ~8 lines
4. ISO conventions                 — pattern angles and extra geometry

All tests are pure-Python, hermetic (no OCC, no network, no DB).
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

# Make src importable when running from the package root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kerf_cad_core.geom.section_cutaway import (
    SectionResult,
    SectionView,
    cut_body_with_plane,
    hatch_cross_section,
    section_view_for_drawing,
)


# ---------------------------------------------------------------------------
# Mesh factories for analytic test bodies
# ---------------------------------------------------------------------------

def _make_box_mesh(
    ox: float = 0.0, oy: float = 0.0, oz: float = 0.0,
    dx: float = 10.0, dy: float = 10.0, dz: float = 10.0,
) -> dict:
    """Axis-aligned box as a triangle mesh dict {verts, faces}."""
    verts = [
        [ox,      oy,      oz],
        [ox + dx, oy,      oz],
        [ox + dx, oy + dy, oz],
        [ox,      oy + dy, oz],
        [ox,      oy,      oz + dz],
        [ox + dx, oy,      oz + dz],
        [ox + dx, oy + dy, oz + dz],
        [ox,      oy + dy, oz + dz],
    ]
    # Each face: 2 triangles
    faces = [
        # bottom (z = oz)
        [0, 1, 2], [0, 2, 3],
        # top (z = oz + dz)
        [4, 6, 5], [4, 7, 6],
        # front (y = oy)
        [0, 5, 1], [0, 4, 5],
        # back (y = oy + dy)
        [2, 7, 3], [2, 6, 7],  # corrected winding
        # right (x = ox + dx)
        [1, 6, 2], [1, 5, 6],
        # left (x = ox)
        [0, 3, 7], [0, 7, 4],
    ]
    return {"verts": verts, "faces": faces}


def _make_cylinder_mesh(
    axis_pt=(0.0, 0.0, 0.0),
    axis_dir=(0.0, 0.0, 1.0),
    radius: float = 0.5,
    height: float = 2.0,
    n_theta: int = 64,
    n_z: int = 8,
) -> dict:
    """A closed cylinder mesh (lateral + caps)."""
    cx, cy, cz = axis_pt
    verts = []
    faces = []

    # Lateral surface vertices
    for iz in range(n_z + 1):
        z = cz + height * iz / n_z
        for it in range(n_theta):
            theta = 2 * math.pi * it / n_theta
            x = cx + radius * math.cos(theta)
            y = cy + radius * math.sin(theta)
            verts.append([x, y, z])

    # Lateral triangles
    for iz in range(n_z):
        for it in range(n_theta):
            it_next = (it + 1) % n_theta
            a = iz * n_theta + it
            b = iz * n_theta + it_next
            c = (iz + 1) * n_theta + it
            d = (iz + 1) * n_theta + it_next
            faces.append([a, b, d])
            faces.append([a, d, c])

    # Bottom cap (z = cz): fan from centre
    bot_centre_idx = len(verts)
    verts.append([cx, cy, cz])
    for it in range(n_theta):
        it_next = (it + 1) % n_theta
        a = 0 * n_theta + it
        b = 0 * n_theta + it_next
        faces.append([bot_centre_idx, b, a])

    # Top cap (z = cz + height): fan from centre
    top_centre_idx = len(verts)
    verts.append([cx, cy, cz + height])
    for it in range(n_theta):
        it_next = (it + 1) % n_theta
        a = n_z * n_theta + it
        b = n_z * n_theta + it_next
        faces.append([top_centre_idx, a, b])

    return {"verts": verts, "faces": faces}


# ---------------------------------------------------------------------------
# Helper: build a simple 10×10 rectangular 2D loop for hatch tests
# ---------------------------------------------------------------------------

def _rect_loop_2d(
    x0: float = 0.0, y0: float = 0.0,
    x1: float = 10.0, y1: float = 10.0,
) -> list:
    """Return a rectangular 2-D loop as [[u, v], ...] (4 corners)."""
    return [
        [x0, y0],
        [x1, y0],
        [x1, y1],
        [x0, y1],
    ]


# ---------------------------------------------------------------------------
# Test 1 — Cube section by midplane  (z = 5)
# ---------------------------------------------------------------------------

class TestCubeSectionMidplane:
    """10×10×10 cube cut by plane z=5.

    Expected:
      - visible half (positive side, z >= 5): 10×10×5 box
      - cross_section_2d: single loop of 4 corners spanning 10×10
    """

    def setup_method(self):
        self.body = _make_box_mesh(dx=10, dy=10, dz=10)
        self.plane = {"normal": [0, 0, 1], "point": [0, 0, 5]}
        self.result = cut_body_with_plane(self.body, self.plane, side="positive")

    def test_ok(self):
        assert self.result.ok, self.result.reason

    def test_plane_normal_stored(self):
        n = self.result.plane_normal
        assert len(n) == 3
        assert abs(n[2] - 1.0) < 1e-10, f"Expected n=[0,0,1], got {n}"

    def test_plane_d_stored(self):
        assert abs(self.result.plane_d - 5.0) < 1e-9

    def test_visible_half_z_range(self):
        """All *used* vertices in the kept half should have z >= 5.0 (within tol).

        The clipping routine may allocate the full original vertex array before
        appending new interpolated verts; we only inspect vertices that are
        actually referenced by the output faces.
        """
        verts = self.result.visible_body_half["verts"]
        faces = self.result.visible_body_half["faces"]
        assert len(verts) > 0, "no vertices in half body"
        assert len(faces) > 0, "no faces in half body"
        # Collect only referenced vertex indices
        used_indices = {idx for face in faces for idx in face}
        for idx in used_indices:
            v = verts[idx]
            assert v[2] >= 5.0 - 1e-6, (
                f"Used vertex[{idx}] {v} is below the cut plane z=5"
            )

    def test_cross_section_exists(self):
        """At least one 2-D loop in the cross-section."""
        loops = self.result.cross_section_2d
        assert len(loops) >= 1, "Expected at least one cross-section loop"

    def test_cross_section_is_10x10(self):
        """The cross-section bounding box should span 10×10 in the cut plane."""
        loops = self.result.cross_section_2d
        all_pts = [pt for loop in loops for pt in loop]
        assert len(all_pts) >= 4, "Expected at least 4 points in cross-section"

        arr = np.array(all_pts, dtype=float)
        u_range = float(arr[:, 0].max() - arr[:, 0].min())
        v_range = float(arr[:, 1].max() - arr[:, 1].min())

        # The cross-section of a 10×10×10 cube at z=5 is a 10×10 square
        assert abs(u_range - 10.0) < 0.5, f"u_range={u_range:.3f}, expected ~10"
        assert abs(v_range - 10.0) < 0.5, f"v_range={v_range:.3f}, expected ~10"

    def test_hatch_present(self):
        """Hatch list should be non-empty and contain lines."""
        hatched = self.result.hatched_2d
        assert len(hatched) >= 1
        total_lines = sum(len(h.get("lines", [])) for h in hatched)
        assert total_lines > 0, "Expected hatch lines in the 10×10 cross-section"

    def test_side_attribute(self):
        assert self.result.visible_body_half.get("side") == "positive"

    def test_negative_side(self):
        """Cutting the negative side: all *used* vertices should have z <= 5."""
        neg = cut_body_with_plane(self.body, self.plane, side="negative")
        assert neg.ok
        verts = neg.visible_body_half["verts"]
        faces = neg.visible_body_half["faces"]
        assert len(verts) > 0
        assert len(faces) > 0
        used_indices = {idx for face in faces for idx in face}
        for idx in used_indices:
            v = verts[idx]
            assert v[2] <= 5.0 + 1e-6, (
                f"Used vertex[{idx}] z={v[2]:.4f} is above the cut plane z=5"
            )


# ---------------------------------------------------------------------------
# Test 2 — Cylinder section by midplane  (y = 0)
# ---------------------------------------------------------------------------

class TestCylinderSectionMidplane:
    """Unit cylinder (r=0.5, h=2) cut by plane y=0.

    Expected cross_section_2d:
      In the (x, z) projected plane the rectangle is 2r × h = 1.0 × 2.0.
    """

    def setup_method(self):
        # Cylinder at origin, r=0.5, h=2 (unit diameter, 2-unit height)
        self.body = _make_cylinder_mesh(
            axis_pt=(0.0, 0.0, 0.0),
            radius=0.5,
            height=2.0,
            n_theta=128,
            n_z=16,
        )
        self.plane = {"normal": [0, 1, 0], "point": [0, 0, 0]}
        self.result = cut_body_with_plane(self.body, self.plane, side="positive")

    def test_ok(self):
        assert self.result.ok, self.result.reason

    def test_cross_section_exists(self):
        loops = self.result.cross_section_2d
        assert len(loops) >= 1, "Expected cross-section loop(s)"

    def test_cross_section_width_height(self):
        """Cross-section at y=0 of a cylinder r=0.5, h=2 is ~1.0 wide × 2.0 tall."""
        loops = self.result.cross_section_2d
        all_pts = [pt for loop in loops for pt in loop]
        assert len(all_pts) >= 4

        arr = np.array(all_pts, dtype=float)
        u_range = float(arr[:, 0].max() - arr[:, 0].min())
        v_range = float(arr[:, 1].max() - arr[:, 1].min())

        # The diameter is 2*r = 1.0 (x-direction in the cut plane)
        # The height is 2.0 (z-direction in the cut plane)
        # We allow ±15% tolerance for mesh discretisation
        assert abs(u_range - 1.0) < 0.2, f"width={u_range:.3f}, expected ~1.0 (2r)"
        assert abs(v_range - 2.0) < 0.4, f"height={v_range:.3f}, expected ~2.0"

    def test_visible_half_y_positive(self):
        """Kept half *used* vertices should all have y >= 0 (positive side of y=0)."""
        verts = self.result.visible_body_half["verts"]
        faces = self.result.visible_body_half["faces"]
        assert len(verts) > 0
        assert len(faces) > 0
        used_indices = {idx for face in faces for idx in face}
        for idx in used_indices:
            v = verts[idx]
            assert v[1] >= -1e-6, (
                f"Used vertex[{idx}] y={v[1]:.4f} < 0 in positive half"
            )


# ---------------------------------------------------------------------------
# Test 3 — Hatch density oracle
# ---------------------------------------------------------------------------

class TestHatchDensity:
    """hatch_cross_section on a 10×10 square with spacing=2.0.

    ISO 128-30 iron = 45°. The diagonal coverage of a 10×10 square:
      diagonal = 10*sqrt(2) ≈ 14.14
      n_lines  ≈ ceil(diagonal / spacing) ≈ ceil(14.14 / 2) = 8

    We require n_lines in [6, 12] (generous for polygon clipping edge effects).
    """

    def setup_method(self):
        self.loop_2d = [_rect_loop_2d(0, 0, 10, 10)]
        self.plane = {"normal": [0, 0, 1], "d": 0.0}

    def test_iron_hatch_count(self):
        hatched = hatch_cross_section(
            self.loop_2d, self.plane,
            hatch_pattern="ISO128-30_iron",
            spacing=2.0,
        )
        assert len(hatched) == 1
        lines = hatched[0]["lines"]
        n = len(lines)
        # Expected ≈ 8 — allow 6..12 for clipping boundary effects
        assert 6 <= n <= 12, (
            f"Hatch line count {n} out of expected range [6, 12] "
            f"(ISO 128-30 §6 oracle: ceil(10√2/2) = 8)"
        )

    def test_iron_hatch_angle_45(self):
        hatched = hatch_cross_section(
            self.loop_2d, self.plane,
            hatch_pattern="ISO128-30_iron",
            spacing=2.0,
        )
        assert hatched[0]["angle_deg"] == pytest.approx(45.0)

    def test_hatch_lines_inside_bbox(self):
        """All hatch line endpoints must be inside the 10×10 bounding box."""
        hatched = hatch_cross_section(
            self.loop_2d, self.plane,
            hatch_pattern="ISO128-30_iron",
            spacing=2.0,
        )
        for line in hatched[0]["lines"]:
            for pt in [line["start"], line["end"]]:
                assert -0.5 <= pt[0] <= 10.5, f"u={pt[0]} out of [0,10]"
                assert -0.5 <= pt[1] <= 10.5, f"v={pt[1]} out of [0,10]"

    def test_hatch_lines_not_degenerate(self):
        """Each line segment must have positive length."""
        hatched = hatch_cross_section(
            self.loop_2d, self.plane,
            hatch_pattern="ISO128-30_iron",
            spacing=2.0,
        )
        for line in hatched[0]["lines"]:
            s = np.array(line["start"])
            e = np.array(line["end"])
            assert np.linalg.norm(e - s) > 1e-6, f"Degenerate line: {line}"


# ---------------------------------------------------------------------------
# Test 4 — ISO conventions: angles and extra geometry
# ---------------------------------------------------------------------------

class TestISOConventions:
    """Verify ISO 128-30 material pattern definitions."""

    def setup_method(self):
        self.loop = [_rect_loop_2d(0, 0, 10, 10)]
        self.plane = {"normal": [0, 0, 1], "d": 0.0}

    def _hatch(self, pattern: str) -> list:
        return hatch_cross_section(
            self.loop, self.plane,
            hatch_pattern=pattern,
            spacing=2.0,
        )

    # ---- Iron: 45° parallel lines ----
    def test_iron_angle_45(self):
        h = self._hatch("ISO128-30_iron")
        assert h[0]["angle_deg"] == pytest.approx(45.0), (
            "ISO 128-30 iron must be 45°"
        )

    def test_iron_no_dots(self):
        h = self._hatch("ISO128-30_iron")
        assert h[0]["dots"] == [], "Iron pattern must not have dot decorations"

    def test_iron_has_lines(self):
        h = self._hatch("ISO128-30_iron")
        assert len(h[0]["lines"]) > 0, "Iron pattern must produce hatch lines"

    # ---- Concrete: 45° lines + dots ----
    def test_concrete_angle_45(self):
        h = self._hatch("concrete")
        assert h[0]["angle_deg"] == pytest.approx(45.0), (
            "Concrete pattern must use 45° lines per ISO 128-30"
        )

    def test_concrete_has_dots(self):
        h = self._hatch("concrete")
        assert len(h[0]["dots"]) > 0, (
            "Concrete pattern must include dot scatter per ISO 128-30"
        )

    def test_concrete_dot_structure(self):
        h = self._hatch("concrete")
        for dot in h[0]["dots"]:
            assert "center" in dot
            assert "radius" in dot
            assert len(dot["center"]) == 2
            assert dot["radius"] > 0

    # ---- Plastic: horizontal (0°) lines ----
    def test_plastic_angle_0(self):
        h = self._hatch("plastic")
        assert h[0]["angle_deg"] == pytest.approx(0.0), (
            "Plastic/elastomer pattern must be horizontal (0°) per ISO 128-30"
        )

    def test_plastic_no_dots(self):
        h = self._hatch("plastic")
        assert h[0]["dots"] == [], "Plastic pattern must not have dot decorations"

    def test_plastic_has_lines(self):
        h = self._hatch("plastic")
        assert len(h[0]["lines"]) > 0, "Plastic pattern must produce hatch lines"

    # ---- Aliases ----
    def test_ansi31_alias(self):
        """'ansi31' should behave identically to 'ISO128-30_iron'."""
        h_iron = self._hatch("ISO128-30_iron")
        h_alias = self._hatch("ansi31")
        assert h_alias[0]["angle_deg"] == h_iron[0]["angle_deg"]
        assert h_alias[0]["dots"] == []


# ---------------------------------------------------------------------------
# Test 5 — section_view_for_drawing integration
# ---------------------------------------------------------------------------

class TestSectionViewForDrawing:
    """End-to-end section view construction."""

    def setup_method(self):
        self.body = _make_box_mesh(dx=10, dy=10, dz=10)
        self.plane = {"normal": [0, 0, 1], "point": [0, 0, 5]}

    def test_ok(self):
        sv = section_view_for_drawing(self.body, self.plane, drawing_scale=1.0)
        assert sv.ok, sv.reason

    def test_section_id(self):
        sv = section_view_for_drawing(self.body, self.plane, section_id="B-B")
        assert sv.section_id == "B-B"

    def test_drawing_scale_stored(self):
        sv = section_view_for_drawing(self.body, self.plane, drawing_scale=0.5)
        assert sv.drawing_scale == pytest.approx(0.5)

    def test_cutting_plane_marker(self):
        sv = section_view_for_drawing(self.body, self.plane)
        m = sv.cutting_plane_marker
        assert "line_start" in m
        assert "line_end" in m
        assert m["style"] == "chain_line"

    def test_arrow_indicators(self):
        sv = section_view_for_drawing(self.body, self.plane)
        arrows = sv.arrow_indicators
        assert len(arrows) == 2, "Bertoline §11: two arrow indicators"
        for arrow in arrows:
            assert "origin" in arrow
            assert "direction" in arrow
            assert "label" in arrow

    def test_nested_section_result(self):
        sv = section_view_for_drawing(self.body, self.plane)
        sr = sv.section_result
        assert sr.ok
        assert len(sr.cross_section_2d) >= 1
        assert len(sr.hatched_2d) >= 1

    def test_concrete_pattern(self):
        sv = section_view_for_drawing(
            self.body, self.plane,
            hatch_pattern="concrete",
            hatch_spacing=2.0,
        )
        assert sv.ok
        has_dots = any(
            len(h.get("dots", [])) > 0
            for h in sv.section_result.hatched_2d
        )
        assert has_dots, "Concrete hatch must include dots"

    def test_plastic_pattern_horizontal(self):
        sv = section_view_for_drawing(
            self.body, self.plane,
            hatch_pattern="plastic",
        )
        assert sv.ok
        for h in sv.section_result.hatched_2d:
            assert h["angle_deg"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 6 — Never-raise guarantee
# ---------------------------------------------------------------------------

class TestNeverRaise:
    """All public functions must return an error result rather than raise."""

    def test_cut_body_bad_plane(self):
        body = _make_box_mesh()
        result = cut_body_with_plane(body, {"normal": [0, 0, 0], "d": 0})
        assert isinstance(result, SectionResult)
        assert not result.ok

    def test_cut_body_bad_side(self):
        body = _make_box_mesh()
        result = cut_body_with_plane(body, {"normal": [0, 0, 1], "d": 5}, side="invalid")
        assert isinstance(result, SectionResult)
        assert not result.ok

    def test_hatch_empty_loops(self):
        result = hatch_cross_section([], {"normal": [0, 0, 1], "d": 0})
        assert isinstance(result, list)

    def test_section_view_bad_plane(self):
        sv = section_view_for_drawing(
            _make_box_mesh(),
            {"normal": [0, 0, 0], "point": [0, 0, 5]},
        )
        assert isinstance(sv, SectionView)
        assert not sv.ok
