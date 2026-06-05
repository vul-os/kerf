"""
Oracle tests for the DSTV NC1 steel-fabrication NC file writer.

DSTV NC standard reference
---------------------------
DSTV NC — Datenaustausch für numerisch gesteuerte Maschinen,
Deutscher Stahlbau-Verband (DSTV), §3 File Structure.
DIN 18800-7:2002 Stahlbauten: Ausführung und Herstellerqualifikation.

Oracle geometry used in round-trip tests
-----------------------------------------
HEB 200 column, 5 000 mm long:
  - Profile: "I HEB 200"
  - Flange: 200 mm wide × 15 mm thick
  - Web: 200 mm height × 9 mm thick
  - 4 bolt holes on top flange (face='o'), Ø22 mm
    at x = 250, 500, 750, 1000 mm, y = ±75 mm from centreline
  - Cope (outer contour, AK) on front face (v) at start end:
    rectangle 100 mm wide × 50 mm deep
  - Part mark "P100" at face='o', x=2500 mm, y=0 mm

Expected NC1 content (verified against DSTV NC §3 field positions):
  - ST block: 12 data lines after "ST" keyword
  - BO block: one "BO" header + 4 hole lines (face  x  y  diameter)
  - AK block: "AK v" + 4 vertices for the rectangular cope
  - SI block: "SI" + 1 stamp line
  - EN terminator
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_heb200_member():
    """Return an NC1Member for HEB 200, 5000 mm long with representative features."""
    from kerf_structural.dstv_nc1 import (
        NC1Member, NC1Hole, NC1ContourPoint, NC1Contour, NC1Stamp
    )
    return NC1Member(
        order_no="ORD-001",
        drawing_no="DWG-A1",
        pos_no="P100",
        quantity=4,
        profile="I HEB 200",
        material="S355JR",
        length_mm=5000.0,
        flange_width_mm=200.0,
        flange_thickness_mm=15.0,
        web_height_mm=200.0,
        web_thickness_mm=9.0,
        holes=[
            NC1Hole(face="o", x_mm=250.0,  y_mm= 75.0, diameter_mm=22.0),
            NC1Hole(face="o", x_mm=250.0,  y_mm=-75.0, diameter_mm=22.0),
            NC1Hole(face="o", x_mm=500.0,  y_mm= 75.0, diameter_mm=22.0),
            NC1Hole(face="o", x_mm=500.0,  y_mm=-75.0, diameter_mm=22.0),
        ],
        outer_contours=[
            NC1Contour(
                face="v",
                points=[
                    NC1ContourPoint(x_mm=0.0,   y_mm=0.0),
                    NC1ContourPoint(x_mm=100.0, y_mm=0.0),
                    NC1ContourPoint(x_mm=100.0, y_mm=50.0),
                    NC1ContourPoint(x_mm=0.0,   y_mm=50.0),
                ],
            )
        ],
        stamps=[
            NC1Stamp(face="o", x_mm=2500.0, y_mm=0.0, text="P100", size_mm=10.0)
        ],
    )


def _run(coro):
    return asyncio.run(coro)


def _ctx():
    try:
        from kerf_structural._compat import ProjectCtx
    except ImportError:
        from types import SimpleNamespace
        return SimpleNamespace(pool=None, project_id=None)
    return ProjectCtx()


def _call_tool(payload: dict) -> dict:
    from kerf_structural.dstv_nc1_tool import run_dstv_nc1
    raw = _run(run_dstv_nc1(_ctx(), json.dumps(payload).encode()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. Data model validation
# ---------------------------------------------------------------------------

class TestDataModelValidation:
    """NC1Hole / NC1Contour / NC1Member validation guards."""

    def test_nc1_hole_rejects_invalid_face(self):
        from kerf_structural.dstv_nc1 import NC1Hole
        with pytest.raises(ValueError, match="face"):
            NC1Hole(face="z", x_mm=100.0, y_mm=0.0, diameter_mm=22.0)

    def test_nc1_hole_rejects_zero_diameter(self):
        from kerf_structural.dstv_nc1 import NC1Hole
        with pytest.raises(ValueError, match="diameter_mm"):
            NC1Hole(face="o", x_mm=100.0, y_mm=0.0, diameter_mm=0.0)

    def test_nc1_hole_rejects_negative_diameter(self):
        from kerf_structural.dstv_nc1 import NC1Hole
        with pytest.raises(ValueError, match="diameter_mm"):
            NC1Hole(face="o", x_mm=100.0, y_mm=0.0, diameter_mm=-5.0)

    def test_nc1_hole_rejects_negative_slot_length(self):
        from kerf_structural.dstv_nc1 import NC1Hole
        with pytest.raises(ValueError, match="slot_length_mm"):
            NC1Hole(face="o", x_mm=100.0, y_mm=0.0, diameter_mm=22.0, slot_length_mm=-1.0)

    def test_nc1_contour_rejects_invalid_face(self):
        from kerf_structural.dstv_nc1 import NC1Contour, NC1ContourPoint
        with pytest.raises(ValueError, match="face"):
            NC1Contour(face="x", points=[
                NC1ContourPoint(0, 0), NC1ContourPoint(100, 0), NC1ContourPoint(100, 50),
            ])

    def test_nc1_contour_rejects_fewer_than_3_points(self):
        from kerf_structural.dstv_nc1 import NC1Contour, NC1ContourPoint
        with pytest.raises(ValueError, match="3 points"):
            NC1Contour(face="o", points=[
                NC1ContourPoint(0, 0), NC1ContourPoint(100, 0),
            ])

    def test_nc1_member_rejects_zero_length(self):
        from kerf_structural.dstv_nc1 import NC1Member
        with pytest.raises(ValueError, match="length_mm"):
            NC1Member(
                order_no="X", drawing_no="X", pos_no="X", quantity=1,
                profile="I HEB 200", material="S355JR",
                length_mm=0.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
                web_height_mm=200.0, web_thickness_mm=9.0,
            )

    def test_nc1_member_rejects_zero_web_height(self):
        from kerf_structural.dstv_nc1 import NC1Member
        with pytest.raises(ValueError, match="web_height_mm"):
            NC1Member(
                order_no="X", drawing_no="X", pos_no="X", quantity=1,
                profile="I HEB 200", material="S355JR",
                length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
                web_height_mm=0.0, web_thickness_mm=9.0,
            )

    def test_nc1_member_rejects_zero_quantity(self):
        from kerf_structural.dstv_nc1 import NC1Member
        with pytest.raises(ValueError, match="quantity"):
            NC1Member(
                order_no="X", drawing_no="X", pos_no="X", quantity=0,
                profile="I HEB 200", material="S355JR",
                length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
                web_height_mm=200.0, web_thickness_mm=9.0,
            )


# ---------------------------------------------------------------------------
# 2. ST block round-trip oracle tests
# ---------------------------------------------------------------------------

class TestSTBlockRoundTrip:
    """Parse the ST block back out and compare to the input data."""

    def test_order_no_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["order_no"] == "ORD-001"

    def test_drawing_no_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["drawing_no"] == "DWG-A1"

    def test_pos_no_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["pos_no"] == "P100"

    def test_quantity_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["quantity"] == 4

    def test_profile_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["profile"] == "I HEB 200"

    def test_material_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["material"] == "S355JR"

    def test_length_mm_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["length_mm"] == pytest.approx(5000.0)

    def test_saw_length_defaults_to_length(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["saw_length_mm"] == pytest.approx(5000.0)

    def test_saw_length_override(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        m.saw_length_mm = 5010.5
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["saw_length_mm"] == pytest.approx(5010.5)

    def test_flange_width_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["flange_width_mm"] == pytest.approx(200.0)

    def test_flange_thickness_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["flange_thickness_mm"] == pytest.approx(15.0)

    def test_web_height_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["web_height_mm"] == pytest.approx(200.0)

    def test_web_thickness_round_trips(self):
        from kerf_structural.dstv_nc1 import write_nc1, parse_nc1_header
        m = _make_heb200_member()
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["web_thickness_mm"] == pytest.approx(9.0)

    def test_parse_raises_on_missing_st_block(self):
        from kerf_structural.dstv_nc1 import parse_nc1_header
        with pytest.raises(ValueError, match="No ST block"):
            parse_nc1_header("not a valid nc1 file\n")

    def test_fractional_length_preserved_3dp(self):
        """Length with up to 3 decimal places must survive the round-trip."""
        from kerf_structural.dstv_nc1 import NC1Member, write_nc1, parse_nc1_header
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I IPE 300", material="S275JR",
            length_mm=4567.125,
            flange_width_mm=150.0, flange_thickness_mm=10.7,
            web_height_mm=300.0, web_thickness_mm=7.1,
        )
        hdr = parse_nc1_header(write_nc1(m))
        assert hdr["length_mm"] == pytest.approx(4567.125, abs=1e-3)


# ---------------------------------------------------------------------------
# 3. BO block — hole coordinates on correct face
# ---------------------------------------------------------------------------

class TestBOBlockHoles:
    """Verify that hole coordinates appear in the BO block, on the correct face."""

    def _get_bo_lines(self, nc1_text: str) -> list[str]:
        lines = nc1_text.splitlines()
        in_bo = False
        bo_data = []
        for line in lines:
            if line.strip() == "BO":
                in_bo = True
                continue
            if in_bo and line.strip() and not line[0].isdigit() and not line[0] in "ouvhae":
                break  # next block keyword
            if in_bo and line.strip():
                bo_data.append(line.strip())
        return bo_data

    def test_bo_block_present(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        assert "\nBO\n" in nc1

    def test_bo_contains_four_holes(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        bo_lines = self._get_bo_lines(write_nc1(m))
        assert len(bo_lines) == 4

    def test_bo_holes_on_top_face(self):
        """All 4 oracle holes are on face 'o' (top flange)."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        bo_lines = self._get_bo_lines(write_nc1(m))
        for line in bo_lines:
            assert line.startswith("o"), f"Expected face 'o', got: {line!r}"

    def test_bo_first_hole_coordinates(self):
        """Oracle: first hole at x=250.0, y=75.0, diameter=22.0."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        bo_lines = self._get_bo_lines(write_nc1(m))
        # line format: "o  250  75  22"
        parts = bo_lines[0].split()
        assert parts[0] == "o"
        assert float(parts[1]) == pytest.approx(250.0)
        assert float(parts[2]) == pytest.approx(75.0)
        assert float(parts[3]) == pytest.approx(22.0)

    def test_bo_hole_with_negative_y(self):
        """Second oracle hole has y=-75.0; ensure negative coordinate is written."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        bo_lines = self._get_bo_lines(write_nc1(m))
        parts = bo_lines[1].split()
        assert float(parts[2]) == pytest.approx(-75.0)

    def test_bo_absent_when_no_holes(self):
        """When the hole list is empty the BO block must not appear at all."""
        from kerf_structural.dstv_nc1 import NC1Member, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I IPE 300", material="S275JR",
            length_mm=3000.0, flange_width_mm=150.0, flange_thickness_mm=10.7,
            web_height_mm=300.0, web_thickness_mm=7.1,
        )
        nc1 = write_nc1(m)
        assert "BO" not in nc1

    def test_bo_slotted_hole_includes_slot_length(self):
        """Slotted hole writes a 5th field (slot_length_mm)."""
        from kerf_structural.dstv_nc1 import NC1Member, NC1Hole, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 200", material="S355JR",
            length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
            web_height_mm=200.0, web_thickness_mm=9.0,
            holes=[
                NC1Hole(face="o", x_mm=300.0, y_mm=0.0, diameter_mm=22.0, slot_length_mm=40.0),
            ],
        )
        nc1 = write_nc1(m)
        bo_lines = self._get_bo_lines(nc1)
        parts = bo_lines[0].split()
        assert len(parts) == 5
        assert float(parts[4]) == pytest.approx(40.0)

    def test_bo_web_face_v(self):
        """Hole on 'v' (front web) face is written with 'v' identifier."""
        from kerf_structural.dstv_nc1 import NC1Member, NC1Hole, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 200", material="S355JR",
            length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
            web_height_mm=200.0, web_thickness_mm=9.0,
            holes=[
                NC1Hole(face="v", x_mm=1000.0, y_mm=0.0, diameter_mm=26.0),
            ],
        )
        nc1 = write_nc1(m)
        bo_lines = self._get_bo_lines(nc1)
        assert bo_lines[0].startswith("v")

    def test_bo_end_plate_face_a(self):
        """Hole on 'a' (start end) face."""
        from kerf_structural.dstv_nc1 import NC1Member, NC1Hole, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 200", material="S355JR",
            length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
            web_height_mm=200.0, web_thickness_mm=9.0,
            holes=[
                NC1Hole(face="a", x_mm=0.0, y_mm=50.0, diameter_mm=22.0),
            ],
        )
        nc1 = write_nc1(m)
        bo_lines = self._get_bo_lines(nc1)
        assert bo_lines[0].startswith("a")


# ---------------------------------------------------------------------------
# 4. AK block — outer contours (copes / notches)
# ---------------------------------------------------------------------------

class TestAKBlock:
    """Verify AK (outer contour) block content."""

    def _get_ak_block(self, nc1_text: str) -> list[str]:
        lines = nc1_text.splitlines()
        result = []
        in_ak = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("AK"):
                in_ak = True
                result.append(stripped)
                continue
            if in_ak and stripped in ("BO", "IK", "SI", "EN") or (
                stripped and not stripped[0].isdigit() and stripped[0] not in "-" and
                not stripped[0].isspace() and stripped not in ("AK v", "AK o", "AK u", "AK h")
                and in_ak and not stripped[0].isdigit()
            ):
                # stop at next block keyword (not a continuation of AK)
                if stripped in ("BO", "IK", "SI", "EN", "ST"):
                    in_ak = False
                    continue
            if in_ak:
                result.append(stripped)
        return result

    def test_ak_block_present(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        assert "AK v" in nc1

    def test_ak_block_has_correct_face(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        # The single AK contour in oracle data is on face 'v'
        assert "AK v\n" in nc1

    def test_ak_block_has_four_vertices(self):
        """Oracle cope contour: 4 vertices (rectangle)."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        ak_idx = next(i for i, l in enumerate(lines) if l.strip() == "AK v")
        # Count vertex lines until next block keyword
        vertices = []
        for ln in lines[ak_idx + 1:]:
            if not ln.strip():
                continue
            if re.match(r'^[A-Z]', ln.strip()):
                break
            vertices.append(ln.strip())
        assert len(vertices) == 4

    def test_ak_first_vertex_origin(self):
        """Oracle: first cope vertex at (0.0, 0.0)."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        ak_idx = next(i for i, l in enumerate(lines) if l.strip() == "AK v")
        first_vertex = lines[ak_idx + 1].strip()
        parts = first_vertex.split()
        assert float(parts[0]) == pytest.approx(0.0)
        assert float(parts[1]) == pytest.approx(0.0)

    def test_ak_second_vertex_x100(self):
        """Oracle: second cope vertex at (100.0, 0.0)."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        ak_idx = next(i for i, l in enumerate(lines) if l.strip() == "AK v")
        second_vertex = lines[ak_idx + 2].strip()
        parts = second_vertex.split()
        assert float(parts[0]) == pytest.approx(100.0)

    def test_ak_absent_when_no_outer_contours(self):
        """AK block must not appear when no outer contours are defined."""
        from kerf_structural.dstv_nc1 import NC1Member, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I IPE 300", material="S275JR",
            length_mm=3000.0, flange_width_mm=150.0, flange_thickness_mm=10.7,
            web_height_mm=300.0, web_thickness_mm=7.1,
        )
        nc1 = write_nc1(m)
        assert "AK" not in nc1


# ---------------------------------------------------------------------------
# 5. IK block — inner contours
# ---------------------------------------------------------------------------

class TestIKBlock:
    def test_ik_block_written(self):
        from kerf_structural.dstv_nc1 import NC1Member, NC1Contour, NC1ContourPoint, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 200", material="S355JR",
            length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
            web_height_mm=200.0, web_thickness_mm=9.0,
            inner_contours=[
                NC1Contour(
                    face="v",
                    points=[
                        NC1ContourPoint(500.0, -50.0),
                        NC1ContourPoint(600.0, -50.0),
                        NC1ContourPoint(600.0,  50.0),
                        NC1ContourPoint(500.0,  50.0),
                    ],
                )
            ],
        )
        nc1 = write_nc1(m)
        assert "IK v" in nc1

    def test_ik_absent_when_no_inner_contours(self):
        from kerf_structural.dstv_nc1 import NC1Member, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I IPE 300", material="S275JR",
            length_mm=3000.0, flange_width_mm=150.0, flange_thickness_mm=10.7,
            web_height_mm=300.0, web_thickness_mm=7.1,
        )
        nc1 = write_nc1(m)
        assert "IK" not in nc1

    def test_ik_vertices_written_correctly(self):
        from kerf_structural.dstv_nc1 import NC1Member, NC1Contour, NC1ContourPoint, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 200", material="S355JR",
            length_mm=5000.0, flange_width_mm=200.0, flange_thickness_mm=15.0,
            web_height_mm=200.0, web_thickness_mm=9.0,
            inner_contours=[
                NC1Contour(
                    face="v",
                    points=[
                        NC1ContourPoint(200.0,  30.0),
                        NC1ContourPoint(400.0,  30.0),
                        NC1ContourPoint(400.0, -30.0),
                    ],
                )
            ],
        )
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        ik_idx = next(i for i, l in enumerate(lines) if l.strip() == "IK v")
        # Check first vertex
        first = lines[ik_idx + 1].strip().split()
        assert float(first[0]) == pytest.approx(200.0)
        assert float(first[1]) == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# 6. SI block — stamps / part marks
# ---------------------------------------------------------------------------

class TestSIBlock:
    def test_si_block_present(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        assert "\nSI\n" in nc1

    def test_si_stamp_text(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        assert "P100" in nc1

    def test_si_stamp_face(self):
        """Oracle stamp is on top face 'o'."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        si_idx = next(i for i, l in enumerate(lines) if l.strip() == "SI")
        stamp_line = lines[si_idx + 1].strip()
        assert stamp_line.startswith("o")

    def test_si_stamp_coordinates(self):
        """Oracle stamp at x=2500, y=0."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        si_idx = next(i for i, l in enumerate(lines) if l.strip() == "SI")
        parts = lines[si_idx + 1].strip().split()
        assert float(parts[1]) == pytest.approx(2500.0)
        assert float(parts[2]) == pytest.approx(0.0)

    def test_si_stamp_size(self):
        """Oracle stamp size = 10.0 mm."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        si_idx = next(i for i, l in enumerate(lines) if l.strip() == "SI")
        parts = lines[si_idx + 1].strip().split()
        assert float(parts[3]) == pytest.approx(10.0)

    def test_si_absent_when_no_stamps(self):
        from kerf_structural.dstv_nc1 import NC1Member, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I IPE 300", material="S275JR",
            length_mm=3000.0, flange_width_mm=150.0, flange_thickness_mm=10.7,
            web_height_mm=300.0, web_thickness_mm=7.1,
        )
        nc1 = write_nc1(m)
        assert "SI" not in nc1


# ---------------------------------------------------------------------------
# 7. Block ordering and EN terminator
# ---------------------------------------------------------------------------

class TestFileStructure:
    """File-level structure checks: block order + EN terminator."""

    def _block_positions(self, nc1_text: str) -> dict[str, int]:
        positions = {}
        for i, line in enumerate(nc1_text.splitlines()):
            s = line.strip()
            for kw in ("ST", "BO", "AK", "IK", "SI", "EN"):
                if s == kw or s.startswith(f"{kw} "):
                    if kw not in positions:
                        positions[kw] = i
        return positions

    def test_st_before_bo(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        pos = self._block_positions(write_nc1(m))
        assert pos["ST"] < pos["BO"]

    def test_bo_before_ak(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        pos = self._block_positions(write_nc1(m))
        assert pos["BO"] < pos["AK"]

    def test_ak_before_si(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        pos = self._block_positions(write_nc1(m))
        assert pos["AK"] < pos["SI"]

    def test_si_before_en(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        pos = self._block_positions(write_nc1(m))
        assert pos["SI"] < pos["EN"]

    def test_en_terminator_last_line(self):
        """EN must be the last non-empty line."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        last_line = [l for l in nc1.splitlines() if l.strip()][-1]
        assert last_line.strip() == "EN"

    def test_file_ends_with_newline(self):
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        assert nc1.endswith("\n")

    def test_st_block_has_exactly_12_data_lines(self):
        """ST keyword + 12 data lines before the next block keyword."""
        from kerf_structural.dstv_nc1 import write_nc1
        m = _make_heb200_member()
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        st_idx = next(i for i, l in enumerate(lines) if l.strip() == "ST")
        # DSTV block keywords are exactly 2 uppercase ASCII letters, optionally
        # followed by a space + face id (e.g. "AK v").  They are never followed
        # immediately by a hyphen or digit, so use a tight pattern.
        _kw = re.compile(r'^(ST|BO|AK|IK|SI|EN)(\s|$)')
        # Count data lines until next block keyword (skip the "ST" line itself)
        data_count = 0
        for ln in lines[st_idx + 1:]:
            if _kw.match(ln.strip()):
                break
            data_count += 1
        assert data_count == 12

    def test_minimal_member_only_st_and_en(self):
        """A member with no optional blocks should have only ST + EN."""
        from kerf_structural.dstv_nc1 import NC1Member, write_nc1
        m = NC1Member(
            order_no="MIN", drawing_no="D1", pos_no="1", quantity=1,
            profile="FL 100x10", material="S235JR",
            length_mm=1000.0, flange_width_mm=100.0, flange_thickness_mm=0.0,
            web_height_mm=100.0, web_thickness_mm=10.0,
        )
        nc1 = write_nc1(m)
        # Only ST, EN — no BO, AK, IK, SI
        assert "BO" not in nc1
        assert "AK" not in nc1
        assert "IK" not in nc1
        assert "SI" not in nc1
        assert nc1.strip().startswith("ST")
        assert nc1.strip().endswith("EN")


# ---------------------------------------------------------------------------
# 8. Number formatting (_fmt helper)
# ---------------------------------------------------------------------------

class TestNumberFormatting:
    """Verify the _fmt() helper produces clean DSTV-compliant decimal strings."""

    def test_integer_value_no_decimal(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(22.0) == "22"

    def test_one_decimal_no_trailing_zero(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(22.5) == "22.5"

    def test_three_decimal_places(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(22.125) == "22.125"

    def test_trailing_zeros_stripped(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(100.500) == "100.5"

    def test_zero(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(0.0) == "0"

    def test_negative_value(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(-75.0) == "-75"

    def test_negative_fractional(self):
        from kerf_structural.dstv_nc1 import _fmt
        assert _fmt(-75.5) == "-75.5"


# ---------------------------------------------------------------------------
# 9. LLM tool handler — steel_export_dstv_nc1
# ---------------------------------------------------------------------------

class TestLLMToolHandler:
    """Verify the LLM tool spec + dispatch handler."""

    def test_spec_name(self):
        from kerf_structural.dstv_nc1_tool import dstv_nc1_spec
        assert dstv_nc1_spec.name == "steel_export_dstv_nc1"

    def test_tool_happy_path(self):
        result = _call_tool({
            "order_no": "ORD-002",
            "drawing_no": "DWG-B1",
            "pos_no": "B100",
            "quantity": 2,
            "profile": "I HEB 200",
            "material": "S355JR",
            "length_mm": 4000.0,
            "flange_width_mm": 200.0,
            "flange_thickness_mm": 15.0,
            "web_height_mm": 200.0,
            "web_thickness_mm": 9.0,
            "holes": [
                {"face": "o", "x_mm": 200.0, "y_mm": 0.0, "diameter_mm": 22.0},
            ],
        })
        assert result.get("ok") is True
        assert "nc1_text" in result
        assert "ST" in result["nc1_text"]
        assert "BO" in result["nc1_text"]
        assert result["member_summary"]["hole_count"] == 1

    def test_tool_minimal_args(self):
        """Tool works with only required fields."""
        result = _call_tool({
            "order_no": "X",
            "drawing_no": "X",
            "pos_no": "X",
            "profile": "I IPE 300",
            "material": "S275JR",
            "length_mm": 3000.0,
            "web_height_mm": 300.0,
        })
        assert result.get("ok") is True
        assert result["nc1_text"].strip().endswith("EN")

    def test_tool_bad_json(self):
        from kerf_structural.dstv_nc1_tool import run_dstv_nc1
        raw = _run(run_dstv_nc1(_ctx(), b"not-json"))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_invalid_face_returns_bad_args(self):
        result = _call_tool({
            "order_no": "X",
            "drawing_no": "X",
            "pos_no": "X",
            "profile": "I HEB 200",
            "material": "S355JR",
            "length_mm": 3000.0,
            "web_height_mm": 200.0,
            "holes": [
                {"face": "z", "x_mm": 100.0, "y_mm": 0.0, "diameter_mm": 22.0},
            ],
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_with_outer_contour(self):
        result = _call_tool({
            "order_no": "X", "drawing_no": "X", "pos_no": "X",
            "profile": "I HEB 200", "material": "S355JR",
            "length_mm": 5000.0, "web_height_mm": 200.0,
            "flange_width_mm": 200.0, "flange_thickness_mm": 15.0,
            "web_thickness_mm": 9.0,
            "outer_contours": [
                {
                    "face": "v",
                    "points": [
                        {"x_mm": 0.0, "y_mm": 0.0},
                        {"x_mm": 100.0, "y_mm": 0.0},
                        {"x_mm": 100.0, "y_mm": 50.0},
                        {"x_mm": 0.0, "y_mm": 50.0},
                    ],
                }
            ],
        })
        assert result.get("ok") is True
        assert "AK v" in result["nc1_text"]
        assert result["member_summary"]["outer_contour_count"] == 1

    def test_tool_with_inner_contour(self):
        result = _call_tool({
            "order_no": "X", "drawing_no": "X", "pos_no": "X",
            "profile": "I HEB 200", "material": "S355JR",
            "length_mm": 5000.0, "web_height_mm": 200.0,
            "flange_width_mm": 200.0, "flange_thickness_mm": 15.0,
            "web_thickness_mm": 9.0,
            "inner_contours": [
                {
                    "face": "v",
                    "points": [
                        {"x_mm": 500.0, "y_mm": -40.0},
                        {"x_mm": 700.0, "y_mm": -40.0},
                        {"x_mm": 700.0, "y_mm":  40.0},
                        {"x_mm": 500.0, "y_mm":  40.0},
                    ],
                }
            ],
        })
        assert result.get("ok") is True
        assert "IK v" in result["nc1_text"]
        assert result["member_summary"]["inner_contour_count"] == 1

    def test_tool_with_stamp(self):
        result = _call_tool({
            "order_no": "X", "drawing_no": "X", "pos_no": "X",
            "profile": "I HEB 200", "material": "S355JR",
            "length_mm": 5000.0, "web_height_mm": 200.0,
            "stamps": [
                {"face": "o", "x_mm": 2500.0, "y_mm": 0.0, "text": "MARK-42"},
            ],
        })
        assert result.get("ok") is True
        assert "MARK-42" in result["nc1_text"]

    def test_tool_nc1_is_valid_round_trip(self):
        """The nc1_text produced by the tool can be re-parsed by parse_nc1_header."""
        from kerf_structural.dstv_nc1 import parse_nc1_header
        result = _call_tool({
            "order_no": "ORD-999",
            "drawing_no": "DWG-Z1",
            "pos_no": "Z001",
            "quantity": 3,
            "profile": "I IPE 450",
            "material": "S355J2",
            "length_mm": 7200.0,
            "flange_width_mm": 190.0,
            "flange_thickness_mm": 14.6,
            "web_height_mm": 450.0,
            "web_thickness_mm": 9.4,
        })
        assert result.get("ok") is True
        hdr = parse_nc1_header(result["nc1_text"])
        assert hdr["order_no"] == "ORD-999"
        assert hdr["profile"] == "I IPE 450"
        assert hdr["length_mm"] == pytest.approx(7200.0)
        assert hdr["quantity"] == 3


# ---------------------------------------------------------------------------
# 10. Multi-face hole distribution validation
# ---------------------------------------------------------------------------

class TestMultiFaceHoles:
    """Verify holes on multiple faces all appear in the BO block correctly."""

    def test_holes_on_four_faces(self):
        """Holes on o, u, v, h all present in BO block with correct face ids."""
        from kerf_structural.dstv_nc1 import NC1Member, NC1Hole, write_nc1
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 300", material="S355JR",
            length_mm=6000.0, flange_width_mm=300.0, flange_thickness_mm=19.0,
            web_height_mm=300.0, web_thickness_mm=11.0,
            holes=[
                NC1Hole(face="o", x_mm=500.0,  y_mm=100.0,  diameter_mm=22.0),
                NC1Hole(face="u", x_mm=500.0,  y_mm=100.0,  diameter_mm=22.0),
                NC1Hole(face="v", x_mm=1000.0, y_mm=0.0,    diameter_mm=26.0),
                NC1Hole(face="h", x_mm=1000.0, y_mm=0.0,    diameter_mm=26.0),
            ],
        )
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        bo_idx = next(i for i, l in enumerate(lines) if l.strip() == "BO")
        faces_found = set()
        for ln in lines[bo_idx + 1:]:
            s = ln.strip()
            if not s or (s and not s[0] in "ouvhae"):
                break
            faces_found.add(s[0])
        assert faces_found == {"o", "u", "v", "h"}

    def test_hole_x_coordinate_precision(self):
        """x_mm with sub-mm precision must round-trip through _fmt."""
        from kerf_structural.dstv_nc1 import _fmt
        # 3 decimal places maximum, no trailing zeros
        assert _fmt(1234.567) == "1234.567"
        assert _fmt(1234.560) == "1234.56"

    def test_hole_count_matches_bo_data_lines(self):
        """Number of BO data lines must equal len(member.holes)."""
        from kerf_structural.dstv_nc1 import NC1Member, NC1Hole, write_nc1
        holes = [
            NC1Hole(face="o", x_mm=float(i * 200 + 200), y_mm=50.0, diameter_mm=22.0)
            for i in range(8)
        ]
        m = NC1Member(
            order_no="X", drawing_no="X", pos_no="X", quantity=1,
            profile="I HEB 240", material="S355JR",
            length_mm=4000.0, flange_width_mm=240.0, flange_thickness_mm=17.0,
            web_height_mm=240.0, web_thickness_mm=10.0,
            holes=holes,
        )
        nc1 = write_nc1(m)
        lines = nc1.splitlines()
        bo_idx = next(i for i, l in enumerate(lines) if l.strip() == "BO")
        count = 0
        for ln in lines[bo_idx + 1:]:
            s = ln.strip()
            if not s or (s and not s[0] in "ouvhae"):
                break
            count += 1
        assert count == 8
