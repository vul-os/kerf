"""
test_dxf.py — pytest suite for the DXF reader (T-5) and mapper (T-6).

Tests cover:
  T-5: reader  — each supported entity type, INSERT/BLOCK round-trip,
                 encoding detection, unsupported-entity warnings.
  T-6: mapper  — entity→.sketch, text→.drawing, annotation-layer routing,
                 closed-loop detection, INSERT expansion.
"""
from __future__ import annotations

import math
import os
import pytest

from kerf_imports.dxf.reader import read_dxf, read_dxf_bytes
from kerf_imports.dxf.entities import (
    DxfLine, DxfLwPolyline, DxfPolyline, DxfCircle, DxfArc,
    DxfText, DxfInsert, DxfBlock, DxfDocument,
)
from kerf_imports.dxf.mapper import dxf_to_sketch, dxf_to_drawing, dxf_to_both, find_closed_loops

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "dxf")

def _fixture(name: str) -> str:
    return os.path.join(_FIXTURES, name)


# ===========================================================================
# T-5  Reader tests
# ===========================================================================

class TestReaderLine:
    def test_line_from_simple_entities_fixture(self):
        with open(_fixture("simple_entities.dxf"), "r") as f:
            doc = read_dxf(f.read())
        lines = [e for e in doc.entities if isinstance(e, DxfLine)]
        assert len(lines) == 4, f"expected 4 lines, got {len(lines)}"

    def test_line_coordinates(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
LINE
  8
WALLS
 10
1.0
 20
2.0
 11
3.0
 21
4.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        assert len(doc.entities) == 1
        line = doc.entities[0]
        assert isinstance(line, DxfLine)
        assert line.x1 == pytest.approx(1.0)
        assert line.y1 == pytest.approx(2.0)
        assert line.x2 == pytest.approx(3.0)
        assert line.y2 == pytest.approx(4.0)
        assert line.layer == "WALLS"

    def test_line_default_layer(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
LINE
 10
0.0
 20
0.0
 11
10.0
 21
0.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        assert doc.entities[0].layer == "0"


class TestReaderCircle:
    def test_circle_from_fixture(self):
        with open(_fixture("simple_entities.dxf"), "r") as f:
            doc = read_dxf(f.read())
        circles = [e for e in doc.entities if isinstance(e, DxfCircle)]
        assert len(circles) == 1
        c = circles[0]
        assert c.cx == pytest.approx(50.0)
        assert c.cy == pytest.approx(25.0)
        assert c.radius == pytest.approx(10.0)

    def test_circle_zero_radius_skipped(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
CIRCLE
  8
0
 10
5.0
 20
5.0
 40
0.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        assert len([e for e in doc.entities if isinstance(e, DxfCircle)]) == 0
        assert any("non-positive" in w for w in doc.warnings)


class TestReaderArc:
    def test_arc_from_fixture(self):
        with open(_fixture("simple_entities.dxf"), "r") as f:
            doc = read_dxf(f.read())
        arcs = [e for e in doc.entities if isinstance(e, DxfArc)]
        assert len(arcs) == 1
        arc = arcs[0]
        assert arc.cx == pytest.approx(200.0)
        assert arc.cy == pytest.approx(0.0)
        assert arc.radius == pytest.approx(30.0)
        assert arc.start_angle == pytest.approx(0.0)
        assert arc.end_angle == pytest.approx(180.0)

    def test_arc_angles_preserved(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
ARC
  8
0
 10
0.0
 20
0.0
 40
5.0
 50
45.0
 51
270.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        arc = doc.entities[0]
        assert isinstance(arc, DxfArc)
        assert arc.start_angle == pytest.approx(45.0)
        assert arc.end_angle == pytest.approx(270.0)


class TestReaderText:
    def test_text_from_fixture(self):
        with open(_fixture("simple_entities.dxf"), "r") as f:
            doc = read_dxf(f.read())
        texts = [e for e in doc.entities if isinstance(e, DxfText)]
        assert len(texts) == 1
        t = texts[0]
        assert t.value == "Hello DXF"
        assert t.height == pytest.approx(5.0)
        assert t.layer == "TEXT"

    def test_text_position(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
TEXT
  8
NOTES
 10
15.5
 20
25.0
 40
3.5
  1
Test label
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        t = doc.entities[0]
        assert isinstance(t, DxfText)
        assert t.x == pytest.approx(15.5)
        assert t.y == pytest.approx(25.0)
        assert t.value == "Test label"


class TestReaderMText:
    def test_mtext_basic(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
MTEXT
  8
ANNO
 10
0.0
 20
0.0
 40
4.0
  1
Hello World
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        texts = [e for e in doc.entities if isinstance(e, DxfText)]
        assert len(texts) == 1
        assert texts[0].value == "Hello World"

    def test_mtext_strips_formatting(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
MTEXT
  8
0
 10
0.0
 20
0.0
 40
4.0
  1
Part\\PNumber
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        texts = [e for e in doc.entities if isinstance(e, DxfText)]
        assert len(texts) == 1
        assert "\\P" not in texts[0].value


class TestReaderLwPolyline:
    def test_lwpolyline_closed(self):
        with open(_fixture("lwpolyline.dxf"), "r") as f:
            doc = read_dxf(f.read())
        polys = [e for e in doc.entities if isinstance(e, DxfLwPolyline)]
        assert len(polys) == 1
        p = polys[0]
        assert p.closed is True
        assert len(p.points) == 4
        assert p.points[0] == pytest.approx([0.0, 0.0])
        assert p.points[1] == pytest.approx([50.0, 0.0])

    def test_lwpolyline_too_short_skipped(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
LWPOLYLINE
  8
0
 90
1
 70
0
 10
5.0
 20
5.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        assert len([e for e in doc.entities if isinstance(e, DxfLwPolyline)]) == 0
        assert any("fewer than 2" in w for w in doc.warnings)


class TestReaderPolyline:
    def test_r12_polyline_from_fixture(self):
        with open(_fixture("polyline_r12.dxf"), "r") as f:
            doc = read_dxf(f.read())
        polys = [e for e in doc.entities if isinstance(e, DxfPolyline)]
        assert len(polys) == 1
        p = polys[0]
        assert len(p.points) == 3
        assert p.points[0] == pytest.approx([10.0, 10.0])
        assert p.closed is False

    def test_r12_polyline_closed(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
POLYLINE
  8
0
 66
1
 70
1
  0
VERTEX
  8
0
 10
0.0
 20
0.0
  0
VERTEX
  8
0
 10
10.0
 20
0.0
  0
VERTEX
  8
0
 10
5.0
 20
8.0
  0
SEQEND
  8
0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        polys = [e for e in doc.entities if isinstance(e, DxfPolyline)]
        assert len(polys) == 1
        assert polys[0].closed is True
        assert len(polys[0].points) == 3


class TestReaderInsertBlock:
    def test_block_table_parsed(self):
        with open(_fixture("block_insert.dxf"), "r") as f:
            doc = read_dxf(f.read())
        assert "BOLT_HOLE" in doc.blocks
        assert "SCREW_PATTERN" in doc.blocks
        bolt = doc.blocks["BOLT_HOLE"]
        assert len(bolt.entities) == 1
        assert isinstance(bolt.entities[0], DxfCircle)

    def test_insert_entity_in_model_space(self):
        with open(_fixture("block_insert.dxf"), "r") as f:
            doc = read_dxf(f.read())
        inserts = [e for e in doc.entities if isinstance(e, DxfInsert)]
        assert len(inserts) == 1
        assert inserts[0].block_name == "SCREW_PATTERN"
        assert inserts[0].x == pytest.approx(20.0)
        assert inserts[0].y == pytest.approx(20.0)

    def test_expand_inserts_flattens_nested_blocks(self):
        with open(_fixture("block_insert.dxf"), "r") as f:
            doc = read_dxf(f.read())
        flat = doc.expand_inserts()
        circles = [e for e in flat if isinstance(e, DxfCircle)]
        # SCREW_PATTERN has 2 BOLT_HOLE inserts, each with 1 circle
        assert len(circles) == 2

    def test_missing_block_warns(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
INSERT
  8
0
  2
NONEXISTENT
 10
0.0
 20
0.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        flat = doc.expand_inserts()
        assert any("NONEXISTENT" in w for w in doc.warnings)


class TestReaderHeader:
    def test_units_from_header(self):
        with open(_fixture("simple_entities.dxf"), "r") as f:
            doc = read_dxf(f.read())
        assert doc.units == "mm"

    def test_default_units_when_no_header(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
LINE
 10
0.0
 20
0.0
 11
1.0
 21
0.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        assert doc.units == "mm"


class TestReaderEncoding:
    def test_reads_utf8_bytes(self):
        dxf_text = "  0\nSECTION\n  2\nENTITIES\n  0\nENDSEC\n  0\nEOF\n"
        doc = read_dxf_bytes(dxf_text.encode("utf-8"))
        assert isinstance(doc, DxfDocument)

    def test_reads_latin1_bytes(self):
        # Include a latin-1 character (é = 0xE9) — pass as bytes
        dxf_text = "  0\nSECTION\n  2\nENTITIES\n  0\nTEXT\n  8\n0\n 10\n0.0\n 20\n0.0\n 40\n2.5\n  1\ncaf\xe9\n  0\nENDSEC\n  0\nEOF\n"
        raw_bytes = dxf_text.encode("latin-1")
        doc = read_dxf_bytes(raw_bytes)
        texts = [e for e in doc.entities if isinstance(e, DxfText)]
        assert len(texts) == 1
        assert "caf" in texts[0].value


class TestReaderUnsupportedEntity:
    def test_warns_on_unknown_entity(self):
        dxf = """\
  0
SECTION
  2
ENTITIES
  0
SPLINE
  8
0
 10
0.0
 20
0.0
  0
LINE
  8
0
 10
0.0
 20
0.0
 11
5.0
 21
0.0
  0
ENDSEC
  0
EOF
"""
        doc = read_dxf(dxf)
        lines = [e for e in doc.entities if isinstance(e, DxfLine)]
        assert len(lines) == 1  # LINE was still parsed


# ===========================================================================
# T-6  Mapper tests
# ===========================================================================

class TestMapperSketch:
    def test_line_to_sketch_entity(self):
        doc = DxfDocument(entities=[
            DxfLine(x1=0.0, y1=0.0, x2=10.0, y2=0.0)
        ])
        sketch = dxf_to_sketch(doc)
        assert sketch["version"] == 1
        ents = sketch["entities"]
        assert len(ents) == 1
        e = ents[0]
        assert e["type"] == "line"
        assert e["start"] == {"x": 0.0, "y": 0.0}
        assert e["end"] == {"x": 10.0, "y": 0.0}

    def test_circle_to_sketch_entity(self):
        doc = DxfDocument(entities=[
            DxfCircle(cx=5.0, cy=5.0, radius=3.0)
        ])
        sketch = dxf_to_sketch(doc)
        ents = sketch["entities"]
        assert len(ents) == 1
        e = ents[0]
        assert e["type"] == "circle"
        assert e["center"] == {"x": 5.0, "y": 5.0}
        assert e["radius"] == pytest.approx(3.0)

    def test_arc_to_sketch_entity(self):
        doc = DxfDocument(entities=[
            DxfArc(cx=0.0, cy=0.0, radius=10.0, start_angle=0.0, end_angle=90.0)
        ])
        sketch = dxf_to_sketch(doc)
        ents = sketch["entities"]
        assert len(ents) == 1
        e = ents[0]
        assert e["type"] == "arc"
        assert e["center"] == {"x": 0.0, "y": 0.0}
        assert e["radius"] == pytest.approx(10.0)
        assert e["start_angle"] == pytest.approx(0.0)
        assert e["end_angle"] == pytest.approx(90.0)

    def test_lwpolyline_to_sketch_entity(self):
        doc = DxfDocument(entities=[
            DxfLwPolyline(points=[[0.0, 0.0], [10.0, 0.0], [10.0, 5.0]], closed=True)
        ])
        sketch = dxf_to_sketch(doc)
        ents = sketch["entities"]
        assert len(ents) == 1
        e = ents[0]
        assert e["type"] == "polyline"
        assert e["closed"] is True
        assert len(e["points"]) == 3

    def test_polyline_to_sketch_entity(self):
        doc = DxfDocument(entities=[
            DxfPolyline(points=[[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]])
        ])
        sketch = dxf_to_sketch(doc)
        ents = sketch["entities"]
        assert len(ents) == 1
        assert ents[0]["type"] == "polyline"

    def test_text_excluded_from_sketch(self):
        doc = DxfDocument(entities=[
            DxfText(x=0.0, y=0.0, value="label")
        ])
        sketch = dxf_to_sketch(doc)
        assert sketch["entities"] == []

    def test_annotation_layer_excluded_from_sketch(self):
        doc = DxfDocument(entities=[
            DxfLine(x1=0.0, y1=0.0, x2=10.0, y2=0.0, layer="DIMENSIONS"),
            DxfLine(x1=0.0, y1=0.0, x2=10.0, y2=5.0, layer="0"),
        ])
        sketch = dxf_to_sketch(doc)
        # "DIMENSIONS" contains "dim" → annotation layer
        assert len(sketch["entities"]) == 1
        assert sketch["entities"][0]["layer"] == "0"

    def test_sketch_has_plane(self):
        doc = DxfDocument(entities=[DxfLine(x1=0, y1=0, x2=1, y2=0)])
        sketch = dxf_to_sketch(doc)
        assert sketch["plane"] == {"type": "world_xy"}

    def test_sketch_has_constraints_empty(self):
        doc = DxfDocument(entities=[DxfLine(x1=0, y1=0, x2=1, y2=0)])
        sketch = dxf_to_sketch(doc)
        assert sketch["constraints"] == []

    def test_sketch_units_in_dxf_ref(self):
        doc = DxfDocument(entities=[DxfLine(x1=0, y1=0, x2=1, y2=0)], units="inches")
        sketch = dxf_to_sketch(doc)
        assert sketch["dxf_ref"]["units"] == "inches"

    def test_insert_expanded_by_default(self):
        """INSERT entities are expanded; constituent circles appear in sketch."""
        block = DxfBlock(name="HOLE", entities=[DxfCircle(cx=0.0, cy=0.0, radius=3.0)])
        doc = DxfDocument(
            entities=[DxfInsert(block_name="HOLE", x=10.0, y=10.0)],
            blocks={"HOLE": block},
        )
        sketch = dxf_to_sketch(doc, expand_inserts=True)
        circles = [e for e in sketch["entities"] if e["type"] == "circle"]
        assert len(circles) == 1

    def test_insert_not_expanded_when_disabled(self):
        block = DxfBlock(name="HOLE", entities=[DxfCircle(cx=0.0, cy=0.0, radius=3.0)])
        doc = DxfDocument(
            entities=[DxfInsert(block_name="HOLE", x=10.0, y=10.0)],
            blocks={"HOLE": block},
        )
        sketch = dxf_to_sketch(doc, expand_inserts=False)
        inserts = [e for e in sketch["entities"] if e["type"] == "insert"]
        assert len(inserts) == 1
        assert inserts[0]["block_name"] == "HOLE"


class TestMapperDrawing:
    def test_text_goes_to_drawing(self):
        doc = DxfDocument(entities=[
            DxfText(x=5.0, y=10.0, value="Title", height=4.0, layer="TITLE")
        ])
        drawing = dxf_to_drawing(doc)
        sheets = drawing["sheets"]
        assert len(sheets) == 1
        anns = sheets[0]["annotations"]
        assert len(anns) == 1
        a = anns[0]
        assert a["type"] == "text"
        assert a["value"] == "Title"
        assert a["x"] == pytest.approx(5.0)
        assert a["y"] == pytest.approx(10.0)
        assert a["height"] == pytest.approx(4.0)

    def test_drawing_has_sheet_frame(self):
        doc = DxfDocument()
        drawing = dxf_to_drawing(doc)
        frame = drawing["sheets"][0]["frame"]
        assert "size" in frame
        assert "orientation" in frame

    def test_drawing_has_empty_views(self):
        doc = DxfDocument()
        drawing = dxf_to_drawing(doc)
        assert drawing["sheets"][0]["views"] == []

    def test_dxf_ref_in_drawing(self):
        doc = DxfDocument(units="inches")
        drawing = dxf_to_drawing(doc)
        assert drawing["dxf_ref"]["units"] == "inches"


class TestMapperDxfToBoth:
    def test_returns_both_payloads(self):
        doc = DxfDocument(entities=[
            DxfLine(x1=0, y1=0, x2=10, y2=0),
            DxfText(x=0, y=0, value="Note"),
        ])
        sketch, drawing = dxf_to_both(doc)
        assert "entities" in sketch
        assert "sheets" in drawing

    def test_line_in_sketch_text_in_drawing(self):
        doc = DxfDocument(entities=[
            DxfLine(x1=0, y1=0, x2=10, y2=0),
            DxfText(x=0, y=0, value="Note"),
        ])
        sketch, drawing = dxf_to_both(doc)
        assert len(sketch["entities"]) == 1
        assert sketch["entities"][0]["type"] == "line"
        assert len(drawing["sheets"][0]["annotations"]) == 1


class TestMapperRoundTrip:
    def test_simple_entities_fixture_round_trip(self):
        """simple_entities.dxf → reader → mapper → both payloads non-empty."""
        with open(os.path.join(_FIXTURES, "simple_entities.dxf"), "r") as f:
            doc = read_dxf(f.read())
        sketch, drawing = dxf_to_both(doc)
        # 4 lines + 1 circle + 1 arc = 6 sketch entities
        assert len(sketch["entities"]) == 6
        # 1 text entity
        assert len(drawing["sheets"][0]["annotations"]) == 1

    def test_block_insert_fixture_round_trip(self):
        """block_insert.dxf with INSERT expansion → 2 circles + 1 line in sketch."""
        with open(_fixture("block_insert.dxf"), "r") as f:
            doc = read_dxf(f.read())
        sketch, drawing = dxf_to_both(doc, expand_inserts=True)
        entity_types = {e["type"] for e in sketch["entities"]}
        assert "circle" in entity_types
        assert "line" in entity_types
        anns = drawing["sheets"][0]["annotations"]
        assert any(a.get("value") == "Assembly Drawing" for a in anns)

    def test_lwpolyline_fixture_round_trip(self):
        with open(_fixture("lwpolyline.dxf"), "r") as f:
            doc = read_dxf(f.read())
        sketch, _ = dxf_to_both(doc)
        polys = [e for e in sketch["entities"] if e["type"] == "polyline"]
        assert len(polys) == 1
        assert polys[0]["closed"] is True

    def test_polyline_r12_fixture_round_trip(self):
        with open(_fixture("polyline_r12.dxf"), "r") as f:
            doc = read_dxf(f.read())
        sketch, _ = dxf_to_both(doc)
        polys = [e for e in sketch["entities"] if e["type"] == "polyline"]
        assert len(polys) == 1
        assert len(polys[0]["points"]) == 3


class TestLoopDetection:
    def test_closed_rectangle_is_one_loop(self):
        """Four lines forming a rectangle → one closed loop."""
        doc = DxfDocument(entities=[
            DxfLine(x1=0, y1=0, x2=10, y2=0),
            DxfLine(x1=10, y1=0, x2=10, y2=10),
            DxfLine(x1=10, y1=10, x2=0, y2=10),
            DxfLine(x1=0, y1=10, x2=0, y2=0),
        ])
        sketch = dxf_to_sketch(doc)
        loops = find_closed_loops(sketch)
        assert len(loops) == 1
        assert len(loops[0]) == 4

    def test_circle_is_trivially_closed_loop(self):
        doc = DxfDocument(entities=[DxfCircle(cx=0, cy=0, radius=5)])
        sketch = dxf_to_sketch(doc)
        loops = find_closed_loops(sketch)
        assert len(loops) == 1
        assert loops[0][0].startswith("e")

    def test_open_polyline_not_a_loop(self):
        doc = DxfDocument(entities=[
            DxfLwPolyline(points=[[0, 0], [10, 0], [10, 5]], closed=False)
        ])
        sketch = dxf_to_sketch(doc)
        loops = find_closed_loops(sketch)
        # open polyline endpoints don't match → no loop
        assert len(loops) == 0

    def test_closed_lwpolyline_is_a_loop(self):
        doc = DxfDocument(entities=[
            DxfLwPolyline(points=[[0, 0], [10, 0], [10, 10], [0, 10]], closed=True)
        ])
        sketch = dxf_to_sketch(doc)
        loops = find_closed_loops(sketch)
        # A closed polyline: end() returns first point, so it chains back to itself
        assert len(loops) == 1

    def test_disconnected_lines_no_loop(self):
        """Two disconnected lines should not form a loop."""
        doc = DxfDocument(entities=[
            DxfLine(x1=0, y1=0, x2=5, y2=0),
            DxfLine(x1=10, y1=0, x2=15, y2=0),
        ])
        sketch = dxf_to_sketch(doc)
        loops = find_closed_loops(sketch)
        assert len(loops) == 0

    def test_arc_completing_rectangle(self):
        """Three lines + one arc forming a D-profile → one loop."""
        r = 5.0
        doc = DxfDocument(entities=[
            # Flat bottom (straight line), along X from (0,0) to (10,0)
            DxfLine(x1=0, y1=0, x2=10, y2=0),
            # Right side up
            DxfLine(x1=10, y1=0, x2=10, y2=r),
            # Left side up
            DxfLine(x1=0, y1=r, x2=0, y2=0),
            # Arc across the top: center (5, r), radius 5, from 0° to 180°
            # start at (10, r), end at (0, r)
            DxfArc(cx=5.0, cy=r, radius=5.0, start_angle=0.0, end_angle=180.0),
        ])
        sketch = dxf_to_sketch(doc)
        loops = find_closed_loops(sketch)
        assert len(loops) >= 1
