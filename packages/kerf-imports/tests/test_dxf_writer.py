"""
test_dxf_writer.py — pytest suite for the general DXF writer (T-7).

Coverage:
  - SECTION/ENDSEC structural validity
  - Round-trip through the existing reader for each entity type
  - LAYER table presence and colors
  - BLOCK/INSERT definition and expansion
  - R12 vs R2004 header differences
  - Empty drawing → minimal valid DXF
  - Mixed-entity round-trip: reader(writer(x)) == x
  - Error recovery (never raises)
  - dwg_note() content
  - Version normalisation
  - SPLINE control points preserved (R2004 only)
  - MTEXT content (R2004)
  - DIMENSION emitted
  - HATCH emitted
  - LEADER emitted
  - ELLIPSE emitted
  - LWPOLYLINE vs POLYLINE by version
  - units header round-trip
  - Explicit layer colors in LAYER table
"""
from __future__ import annotations

import math
import pytest

from kerf_imports.dxf_writer import dxf_export, dxf_export_result, dwg_note
from kerf_imports.dxf.reader import read_dxf
from kerf_imports.dxf.entities import (
    DxfDocument,
    DxfLine,
    DxfLwPolyline,
    DxfPolyline,
    DxfCircle,
    DxfArc,
    DxfText,
    DxfInsert,
    DxfBlock,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sections(dxf_text: str) -> list[str]:
    """Return list of section names found in the DXF text."""
    names = []
    lines = dxf_text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "SECTION" and i > 0:
            # Previous line is the group code; name is two lines ahead
            if i + 2 < len(lines):
                names.append(lines[i + 2].strip())
    return names


def _has_entity(dxf_text: str, entity_type: str) -> bool:
    lines = [l.strip() for l in dxf_text.splitlines()]
    return entity_type.upper() in lines


def _round_trip(doc_or_dict) -> DxfDocument:
    """Write to DXF then re-parse with the reader."""
    text = dxf_export(doc_or_dict, version="R2004")
    return read_dxf(text)


# ===========================================================================
# 1. Structural validity
# ===========================================================================

class TestStructure:
    def test_has_header_section(self):
        text = dxf_export({}, version="R2004")
        assert "HEADER" in _sections(text)

    def test_has_entities_section(self):
        text = dxf_export({}, version="R2004")
        assert "ENTITIES" in _sections(text)

    def test_has_blocks_section(self):
        text = dxf_export({}, version="R2004")
        assert "BLOCKS" in _sections(text)

    def test_has_tables_section(self):
        text = dxf_export({}, version="R2004")
        assert "TABLES" in _sections(text)

    def test_endsec_count_matches_section_count(self):
        text = dxf_export({}, version="R2004")
        n_section = text.count("\nSECTION\n")
        n_endsec  = text.count("\nENDSEC\n")
        assert n_section == n_endsec, (
            f"SECTION count ({n_section}) != ENDSEC count ({n_endsec})"
        )

    def test_ends_with_eof(self):
        text = dxf_export({}, version="R2004")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        assert lines[-1] == "EOF"

    def test_r12_header_version(self):
        text = dxf_export({}, version="R12")
        assert "AC1009" in text

    def test_r2004_header_version(self):
        text = dxf_export({}, version="R2004")
        assert "AC1018" in text

    def test_r12_vs_r2004_header_differ(self):
        r12   = dxf_export({}, version="R12")
        r2004 = dxf_export({}, version="R2004")
        assert "AC1009" in r12
        assert "AC1018" in r2004
        assert "AC1009" not in r2004
        assert "AC1018" not in r12


# ===========================================================================
# 2. Empty drawing → minimal valid DXF
# ===========================================================================

class TestEmptyDrawing:
    def test_empty_dict_is_parseable(self):
        text = dxf_export({})
        doc = read_dxf(text)
        assert isinstance(doc, DxfDocument)
        assert doc.entities == []

    def test_empty_dxfdocument_parseable(self):
        text = dxf_export(DxfDocument())
        doc = read_dxf(text)
        assert isinstance(doc, DxfDocument)
        assert doc.entities == []

    def test_none_entities_key_handled(self):
        text = dxf_export({"entities": None})
        doc = read_dxf(text)
        assert doc.entities == []


# ===========================================================================
# 3. LINE round-trip
# ===========================================================================

class TestLineRoundTrip:
    def test_line_endpoints_preserved(self):
        orig = DxfDocument(entities=[DxfLine(x1=1.0, y1=2.0, x2=3.0, y2=4.0)])
        rt = _round_trip(orig)
        lines = [e for e in rt.entities if isinstance(e, DxfLine)]
        assert len(lines) == 1
        l = lines[0]
        assert l.x1 == pytest.approx(1.0)
        assert l.y1 == pytest.approx(2.0)
        assert l.x2 == pytest.approx(3.0)
        assert l.y2 == pytest.approx(4.0)

    def test_line_layer_preserved(self):
        orig = DxfDocument(entities=[DxfLine(x1=0, y1=0, x2=1, y2=0, layer="WALLS")])
        rt = _round_trip(orig)
        assert rt.entities[0].layer == "WALLS"

    def test_dict_line_round_trip(self):
        drawing = {"entities": [
            {"type": "line", "x1": 5.0, "y1": 6.0, "x2": 7.0, "y2": 8.0, "layer": "0"}
        ]}
        rt = _round_trip(drawing)
        lines = [e for e in rt.entities if isinstance(e, DxfLine)]
        assert len(lines) == 1
        assert lines[0].x1 == pytest.approx(5.0)


# ===========================================================================
# 4. CIRCLE round-trip
# ===========================================================================

class TestCircleRoundTrip:
    def test_circle_center_and_radius_preserved(self):
        orig = DxfDocument(entities=[DxfCircle(cx=10.0, cy=20.0, radius=5.0)])
        rt = _round_trip(orig)
        circles = [e for e in rt.entities if isinstance(e, DxfCircle)]
        assert len(circles) == 1
        c = circles[0]
        assert c.cx == pytest.approx(10.0)
        assert c.cy == pytest.approx(20.0)
        assert c.radius == pytest.approx(5.0)

    def test_circle_layer_preserved(self):
        orig = DxfDocument(entities=[DxfCircle(cx=0, cy=0, radius=3, layer="HOLES")])
        rt = _round_trip(orig)
        c = [e for e in rt.entities if isinstance(e, DxfCircle)][0]
        assert c.layer == "HOLES"


# ===========================================================================
# 5. ARC round-trip
# ===========================================================================

class TestArcRoundTrip:
    def test_arc_angles_preserved(self):
        orig = DxfDocument(entities=[DxfArc(cx=0.0, cy=0.0, radius=10.0,
                                             start_angle=30.0, end_angle=270.0)])
        rt = _round_trip(orig)
        arcs = [e for e in rt.entities if isinstance(e, DxfArc)]
        assert len(arcs) == 1
        a = arcs[0]
        assert a.start_angle == pytest.approx(30.0)
        assert a.end_angle == pytest.approx(270.0)

    def test_arc_center_preserved(self):
        orig = DxfDocument(entities=[DxfArc(cx=5.5, cy=7.5, radius=2.0,
                                             start_angle=0.0, end_angle=90.0)])
        rt = _round_trip(orig)
        a = [e for e in rt.entities if isinstance(e, DxfArc)][0]
        assert a.cx == pytest.approx(5.5)
        assert a.cy == pytest.approx(7.5)


# ===========================================================================
# 6. POLYLINE / LWPOLYLINE round-trip
# ===========================================================================

class TestPolylineRoundTrip:
    def test_lwpolyline_vertices_r2004(self):
        pts = [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0]]
        orig = DxfDocument(entities=[DxfLwPolyline(points=pts, closed=False)])
        rt = _round_trip(orig)
        # Reader reads LWPOLYLINE → DxfLwPolyline
        polys = [e for e in rt.entities if isinstance(e, (DxfLwPolyline, DxfPolyline))]
        assert len(polys) == 1
        assert len(polys[0].points) == 3
        assert polys[0].points[0] == pytest.approx([0.0, 0.0])
        assert polys[0].points[2] == pytest.approx([10.0, 5.0])

    def test_closed_polyline_flag_preserved(self):
        pts = [[0.0, 0.0], [10.0, 0.0], [5.0, 8.0]]
        orig = DxfDocument(entities=[DxfPolyline(points=pts, closed=True)])
        rt = _round_trip(orig)
        polys = [e for e in rt.entities if isinstance(e, (DxfLwPolyline, DxfPolyline))]
        assert polys[0].closed is True

    def test_r12_emits_polyline_not_lwpolyline(self):
        pts = [[0.0, 0.0], [5.0, 0.0]]
        drawing = {"entities": [{"type": "lwpolyline", "points": pts}]}
        text = dxf_export(drawing, version="R12")
        assert "POLYLINE" in text
        # LWPOLYLINE must NOT appear in R12 output
        assert "LWPOLYLINE" not in text

    def test_r2004_emits_lwpolyline(self):
        pts = [[0.0, 0.0], [5.0, 0.0]]
        drawing = {"entities": [{"type": "lwpolyline", "points": pts}]}
        text = dxf_export(drawing, version="R2004")
        assert "LWPOLYLINE" in text


# ===========================================================================
# 7. TEXT round-trip
# ===========================================================================

class TestTextRoundTrip:
    def test_text_value_and_position_preserved(self):
        orig = DxfDocument(entities=[DxfText(x=3.0, y=4.0, value="Hello DXF", height=5.0)])
        rt = _round_trip(orig)
        texts = [e for e in rt.entities if isinstance(e, DxfText)]
        assert len(texts) == 1
        t = texts[0]
        assert t.value == "Hello DXF"
        assert t.x == pytest.approx(3.0)
        assert t.y == pytest.approx(4.0)

    def test_text_height_preserved(self):
        orig = DxfDocument(entities=[DxfText(x=0, y=0, value="A", height=7.5)])
        rt = _round_trip(orig)
        t = [e for e in rt.entities if isinstance(e, DxfText)][0]
        assert t.height == pytest.approx(7.5)


# ===========================================================================
# 8. SPLINE (R2004 only)
# ===========================================================================

class TestSpline:
    def test_spline_entity_emitted_r2004(self):
        drawing = {"entities": [{
            "type": "spline",
            "control_points": [[0, 0], [5, 10], [10, 0], [15, 10]],
            "degree": 3,
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "SPLINE" in text

    def test_spline_not_emitted_r12(self):
        drawing = {"entities": [{
            "type": "spline",
            "control_points": [[0, 0], [5, 10], [10, 0]],
        }]}
        text = dxf_export(drawing, version="R12")
        assert "SPLINE" not in text

    def test_spline_control_points_in_output(self):
        ctrl = [[0.0, 0.0], [5.0, 10.0], [10.0, 0.0]]
        drawing = {"entities": [{
            "type": "spline",
            "control_points": ctrl,
            "degree": 2,
        }]}
        text = dxf_export(drawing, version="R2004")
        # Group code 10 values for control points should appear
        lines = text.splitlines()
        code10_vals = []
        for i, line in enumerate(lines):
            if line.strip() == "10" and i + 1 < len(lines):
                try:
                    code10_vals.append(float(lines[i + 1].strip()))
                except ValueError:
                    pass
        # Should have x-coords: 0.0, 5.0, 10.0 among the code-10 values
        assert 5.0 in code10_vals or any(abs(v - 5.0) < 0.001 for v in code10_vals)


# ===========================================================================
# 9. MTEXT (R2004 only)
# ===========================================================================

class TestMText:
    def test_mtext_emitted_r2004(self):
        drawing = {"entities": [{
            "type": "mtext",
            "x": 0.0, "y": 0.0,
            "value": "Part Number",
            "height": 3.5,
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "MTEXT" in text
        assert "Part Number" in text

    def test_mtext_falls_back_to_text_r12(self):
        drawing = {"entities": [{
            "type": "mtext",
            "x": 0.0, "y": 0.0,
            "value": "Note",
        }]}
        text = dxf_export(drawing, version="R12")
        # R12 has no MTEXT; writer should emit TEXT instead
        assert "TEXT" in text
        assert "MTEXT" not in text


# ===========================================================================
# 10. DIMENSION
# ===========================================================================

class TestDimension:
    def test_dimension_entity_in_output(self):
        drawing = {"entities": [{
            "type": "dimension",
            "dim_type": 1,
            "def_x": 0.0, "def_y": 0.0,
            "ext1_x": 0.0, "ext1_y": 0.0,
            "ext2_x": 50.0, "ext2_y": 0.0,
            "text": "50",
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "DIMENSION" in text

    def test_dimension_in_r12(self):
        drawing = {"entities": [{
            "type": "dimension",
            "dim_type": 0,
            "def_x": 0.0, "def_y": 0.0,
        }]}
        text = dxf_export(drawing, version="R12")
        assert "DIMENSION" in text


# ===========================================================================
# 11. HATCH (R2004 only)
# ===========================================================================

class TestHatch:
    def test_hatch_solid_emitted_r2004(self):
        drawing = {"entities": [{
            "type": "hatch",
            "boundary": [[0, 0], [10, 0], [10, 10], [0, 10]],
            "pattern": "SOLID",
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "HATCH" in text

    def test_hatch_named_pattern(self):
        drawing = {"entities": [{
            "type": "hatch",
            "boundary": [[0, 0], [5, 0], [5, 5], [0, 5]],
            "pattern": "ANSI31",
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "HATCH" in text
        assert "ANSI31" in text


# ===========================================================================
# 12. INSERT / BLOCK
# ===========================================================================

class TestInsertBlock:
    def test_block_definition_in_output(self):
        orig = DxfDocument(
            entities=[DxfInsert(block_name="HOLE", x=10.0, y=20.0)],
            blocks={"HOLE": DxfBlock(name="HOLE", entities=[
                DxfCircle(cx=0.0, cy=0.0, radius=3.0)
            ])},
        )
        text = dxf_export(orig, version="R2004")
        assert "BLOCK" in text
        assert "HOLE" in text

    def test_insert_entity_round_trip(self):
        orig = DxfDocument(
            entities=[DxfInsert(block_name="BOLT", x=5.0, y=5.0)],
            blocks={"BOLT": DxfBlock(name="BOLT", entities=[
                DxfCircle(cx=0.0, cy=0.0, radius=1.5)
            ])},
        )
        rt = _round_trip(orig)
        inserts = [e for e in rt.entities if isinstance(e, DxfInsert)]
        assert len(inserts) == 1
        assert inserts[0].block_name == "BOLT"
        assert inserts[0].x == pytest.approx(5.0)
        assert inserts[0].y == pytest.approx(5.0)

    def test_block_expands_circles(self):
        orig = DxfDocument(
            entities=[DxfInsert(block_name="PAD", x=0.0, y=0.0)],
            blocks={"PAD": DxfBlock(name="PAD", entities=[
                DxfCircle(cx=0.0, cy=0.0, radius=2.0)
            ])},
        )
        rt = _round_trip(orig)
        flat = rt.expand_inserts()
        circles = [e for e in flat if isinstance(e, DxfCircle)]
        assert len(circles) == 1


# ===========================================================================
# 13. LAYER table
# ===========================================================================

class TestLayerTable:
    def test_layer_table_present(self):
        text = dxf_export({"entities": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 0, "layer": "WALLS"}
        ]})
        assert "LAYER" in text

    def test_entity_layer_appears_in_table(self):
        text = dxf_export({"entities": [
            {"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 0, "layer": "BORDER"}
        ]})
        assert "BORDER" in text

    def test_explicit_layer_color(self):
        drawing = {
            "entities": [{"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 0, "layer": "RED_LAYER"}],
            "layers": [{"name": "RED_LAYER", "color": 1, "linetype": "CONTINUOUS"}],
        }
        text = dxf_export(drawing)
        assert "RED_LAYER" in text
        # Color 1 (red) should appear in the LAYER table section
        lines = text.splitlines()
        in_tables = False
        found_color_1 = False
        for i, line in enumerate(lines):
            if line.strip() == "TABLES":
                in_tables = True
            if in_tables and line.strip() == "ENTITIES":
                break
            if in_tables and line.strip() == "62" and i + 1 < len(lines):
                if lines[i + 1].strip() == "1":
                    found_color_1 = True
        assert found_color_1

    def test_default_layer_zero_always_present(self):
        text = dxf_export({})
        assert text.count("\n0\n") > 0 or "     0\n0" in text or "  2\n0\n" in text


# ===========================================================================
# 14. LEADER
# ===========================================================================

class TestLeader:
    def test_leader_emitted_r2004(self):
        drawing = {"entities": [{
            "type": "leader",
            "points": [[0.0, 0.0], [10.0, 10.0], [20.0, 10.0]],
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "LEADER" in text

    def test_leader_falls_back_to_polyline_r12(self):
        drawing = {"entities": [{
            "type": "leader",
            "points": [[0.0, 0.0], [10.0, 10.0]],
        }]}
        text = dxf_export(drawing, version="R12")
        assert "POLYLINE" in text


# ===========================================================================
# 15. ELLIPSE (R2004 only)
# ===========================================================================

class TestEllipse:
    def test_ellipse_emitted_r2004(self):
        drawing = {"entities": [{
            "type": "ellipse",
            "cx": 0.0, "cy": 0.0,
            "major_radius": 10.0, "minor_radius": 5.0,
        }]}
        text = dxf_export(drawing, version="R2004")
        assert "ELLIPSE" in text

    def test_ellipse_not_emitted_r12(self):
        drawing = {"entities": [{
            "type": "ellipse",
            "cx": 0.0, "cy": 0.0,
            "major_radius": 10.0, "minor_radius": 5.0,
        }]}
        text = dxf_export(drawing, version="R12")
        assert "ELLIPSE" not in text


# ===========================================================================
# 16. Units header
# ===========================================================================

class TestUnitsHeader:
    def test_mm_units_code_4(self):
        text = dxf_export({"units": "mm"})
        # $INSUNITS group-70 value 4 = mm
        lines = text.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.strip() == "$INSUNITS" and i + 2 < len(lines):
                val = lines[i + 2].strip()
                if val == "4":
                    found = True
        assert found

    def test_inches_units_code_1(self):
        text = dxf_export({"units": "inches"})
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "$INSUNITS" and i + 2 < len(lines):
                assert lines[i + 2].strip() == "1"
                return
        pytest.fail("$INSUNITS not found in header")


# ===========================================================================
# 17. Error recovery — never raises
# ===========================================================================

class TestErrorRecovery:
    def test_bad_entity_type_silently_skipped(self):
        drawing = {"entities": [
            {"type": "UNKNOWN_ENTITY_XYZ", "layer": "0"},
            {"type": "line", "x1": 0, "y1": 0, "x2": 1, "y2": 0},
        ]}
        text = dxf_export(drawing)
        doc = read_dxf(text)
        lines = [e for e in doc.entities if isinstance(e, DxfLine)]
        assert len(lines) == 1

    def test_export_result_ok_on_success(self):
        result = dxf_export_result({"entities": []})
        assert result["ok"] is True
        assert result["reason"] is None
        assert isinstance(result["dxf"], str)

    def test_export_result_false_on_bad_version(self):
        result = dxf_export_result({}, version="BADVER")
        assert result["ok"] is False
        assert result["reason"] is not None
        # Still returns a minimal valid DXF string
        assert "SECTION" in result["dxf"]
        assert "EOF" in result["dxf"]

    def test_invalid_drawing_type_returns_error(self):
        result = dxf_export_result(12345)
        assert result["ok"] is False
        assert "dxf" in result

    def test_none_entity_fields_use_defaults(self):
        drawing = {"entities": [
            {"type": "circle"}  # no cx/cy/radius
        ]}
        text = dxf_export(drawing)
        assert "CIRCLE" in text


# ===========================================================================
# 18. dwg_note()
# ===========================================================================

class TestDwgNote:
    def test_note_mentions_oda(self):
        note = dwg_note()
        assert "ODA" in note or "oda" in note.lower()

    def test_note_mentions_dxf(self):
        note = dwg_note()
        assert "DXF" in note or "dxf" in note.lower()

    def test_note_is_string(self):
        assert isinstance(dwg_note(), str)


# ===========================================================================
# 19. Mixed-entity round-trip  reader(writer(x)) == x
# ===========================================================================

class TestMixedRoundTrip:
    def test_mixed_entity_set_round_trips(self):
        """A document with line + circle + arc + text + insert round-trips."""
        block = DxfBlock(
            name="MARKER",
            entities=[DxfCircle(cx=0.0, cy=0.0, radius=1.0)],
        )
        orig = DxfDocument(
            entities=[
                DxfLine(x1=0.0, y1=0.0, x2=100.0, y2=0.0, layer="OUTLINE"),
                DxfCircle(cx=50.0, cy=25.0, radius=10.0, layer="HOLES"),
                DxfArc(cx=0.0, cy=0.0, radius=20.0,
                       start_angle=0.0, end_angle=180.0, layer="ARCS"),
                DxfText(x=10.0, y=50.0, value="Title Block", height=4.0),
                DxfInsert(block_name="MARKER", x=30.0, y=30.0),
            ],
            blocks={"MARKER": block},
        )
        rt = _round_trip(orig)

        lines   = [e for e in rt.entities if isinstance(e, DxfLine)]
        circles = [e for e in rt.entities if isinstance(e, DxfCircle)]
        arcs    = [e for e in rt.entities if isinstance(e, DxfArc)]
        texts   = [e for e in rt.entities if isinstance(e, DxfText)]
        inserts = [e for e in rt.entities if isinstance(e, DxfInsert)]

        assert len(lines) == 1
        assert lines[0].x2 == pytest.approx(100.0)

        assert len(circles) == 1
        assert circles[0].radius == pytest.approx(10.0)

        assert len(arcs) == 1
        assert arcs[0].end_angle == pytest.approx(180.0)

        assert len(texts) == 1
        assert texts[0].value == "Title Block"

        assert len(inserts) == 1
        assert inserts[0].block_name == "MARKER"

    def test_lwpolyline_round_trip_r2004(self):
        pts = [[0.0, 0.0], [20.0, 0.0], [20.0, 15.0], [0.0, 15.0]]
        orig = DxfDocument(entities=[DxfLwPolyline(points=pts, closed=True, layer="FRAME")])
        rt = _round_trip(orig)
        polys = [e for e in rt.entities if isinstance(e, (DxfLwPolyline, DxfPolyline))]
        assert len(polys) == 1
        assert polys[0].closed is True
        assert len(polys[0].points) == 4

    def test_polyline_r12_round_trip(self):
        pts = [[1.0, 2.0], [3.0, 4.0], [5.0, 2.0]]
        orig = DxfDocument(entities=[DxfPolyline(points=pts, closed=False)])
        text = dxf_export(orig, version="R12")
        rt = read_dxf(text)
        polys = [e for e in rt.entities if isinstance(e, DxfPolyline)]
        assert len(polys) == 1
        assert polys[0].points[1] == pytest.approx([3.0, 4.0])
