"""
test_sketch_translator.py — T3 Sketch translator tests.

Tests every row of the constraint mapping table from the design doc, plus the
drop-with-warning paths and geometry translation.
"""
from __future__ import annotations

import math
import pytest

from kerf_imports.freecad.types import FCStdObject
from kerf_imports.freecad.sketch import translate_sketch, _CONSTRAINT_TYPE_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sketch_obj(geometry=None, constraints=None, name="Sketch", extra_props=None):
    """Build a minimal FCStdObject representing a Sketcher::SketchObject."""
    props = {}
    if geometry is not None:
        props["Geometry"] = geometry
    if constraints is not None:
        props["Constraints"] = constraints
    if extra_props:
        props.update(extra_props)
    return FCStdObject(
        name=name,
        type="Sketcher::SketchObject",
        label=name,
        properties=props,
    )


def _line(idx, x1=0, y1=0, x2=10, y2=0, construction=False):
    g = {
        "type": "Part::GeomLineSegment",
        "Start": {"x": x1, "y": y1, "z": 0},
        "End": {"x": x2, "y": y2, "z": 0},
    }
    if construction:
        g["construction"] = True
    return g


def _circle(idx, cx=0, cy=0, r=5):
    return {
        "type": "Part::GeomCircle",
        "Center": {"x": cx, "y": cy, "z": 0},
        "Radius": r,
    }


def _arc(idx, cx=0, cy=0, r=5, start=0.0, end=math.pi):
    return {
        "type": "Part::GeomArcOfCircle",
        "Center": {"x": cx, "y": cy, "z": 0},
        "Radius": r,
        "StartAngle": start,
        "EndAngle": end,
    }


def _constraint(type_int, first=0, second=-1, third=-1,
                first_pos=0, second_pos=0, value=None, name=""):
    c = {
        "Type": type_int,
        "First": first,
        "Second": second,
        "Third": third,
        "FirstPos": first_pos,
        "SecondPos": second_pos,
        "Name": name,
    }
    if value is not None:
        c["Value"] = float(value)
    return c


# ---------------------------------------------------------------------------
# Basic smoke test
# ---------------------------------------------------------------------------

class TestTranslateSketchBasic:
    def test_empty_sketch_returns_dict(self):
        obj = _make_sketch_obj(geometry=[], constraints=[])
        result = translate_sketch(obj)
        assert isinstance(result, dict)
        assert "entities" in result
        assert "constraints" in result
        assert "warnings" in result
        assert "plane" in result
        assert "freecad_ref" in result

    def test_empty_sketch_no_warnings(self):
        obj = _make_sketch_obj(geometry=[], constraints=[])
        result = translate_sketch(obj)
        assert result["warnings"] == []

    def test_freecad_ref_populated(self):
        obj = _make_sketch_obj(name="MySketch")
        result = translate_sketch(obj)
        assert result["freecad_ref"]["name"] == "MySketch"
        assert result["freecad_ref"]["type"] == "Sketcher::SketchObject"


# ---------------------------------------------------------------------------
# Geometry translation
# ---------------------------------------------------------------------------

class TestGeometryTranslation:
    def test_line_segment(self):
        geom = [_line(0, 0, 0, 10, 5)]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        entities = translate_sketch(obj)["entities"]
        assert len(entities) == 1
        e = entities[0]
        assert e["type"] == "line"
        assert e["start"] == {"x": 0.0, "y": 0.0}
        assert e["end"] == {"x": 10.0, "y": 5.0}
        assert e["id"] == "g0"

    def test_circle(self):
        geom = [_circle(0, cx=3, cy=4, r=7)]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        entities = translate_sketch(obj)["entities"]
        assert entities[0]["type"] == "circle"
        assert entities[0]["center"] == {"x": 3.0, "y": 4.0}
        assert entities[0]["radius"] == 7.0

    def test_arc(self):
        geom = [_arc(0, cx=1, cy=2, r=3, start=0.0, end=math.pi)]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        entities = translate_sketch(obj)["entities"]
        e = entities[0]
        assert e["type"] == "arc"
        assert e["center"] == {"x": 1.0, "y": 2.0}
        assert e["radius"] == 3.0
        assert abs(e["start_angle"] - 0.0) < 1e-6
        assert abs(e["end_angle"] - 180.0) < 1e-6

    def test_construction_flag_propagated(self):
        geom = [_line(0, construction=True)]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        entities = translate_sketch(obj)["entities"]
        assert entities[0].get("construction") is True

    def test_ellipse_becomes_construction(self):
        geom = [{"type": "Part::GeomEllipse", "Center": {"x": 0, "y": 0, "z": 0}}]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        result = translate_sketch(obj)
        entities = result["entities"]
        assert entities[0]["construction"] is True
        assert any("ellipse" in w for w in result["warnings"])

    def test_bspline_becomes_construction(self):
        geom = [{"type": "Part::GeomBSplineCurve"}]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        result = translate_sketch(obj)
        assert result["entities"][0]["construction"] is True
        assert any("B-spline" in w for w in result["warnings"])

    def test_unknown_geom_emits_warning(self):
        geom = [{"type": "Part::GeomSomethingWeird"}]
        obj = _make_sketch_obj(geometry=geom, constraints=[])
        result = translate_sketch(obj)
        assert any("unrecognised" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Constraint mapping table (one assertion per row)
# ---------------------------------------------------------------------------

class TestConstraintMappingTable:
    """Each test verifies one row of the constraint type mapping table."""

    def _single_constraint(self, type_int, **kwargs):
        geom = [_line(0), _line(1, x1=5, y1=0, x2=5, y2=10)]
        c = _constraint(type_int, **kwargs)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        return translate_sketch(obj)

    # Type 1 – Coincident
    def test_coincident(self):
        result = self._single_constraint(1, first=0, second=1, first_pos=1, second_pos=2)
        cs = result["constraints"]
        assert len(cs) == 1
        assert cs[0]["type"] == "coincident"
        assert cs[0]["first"]["entity_id"] == "g0"
        assert cs[0]["second"]["entity_id"] == "g1"

    # Type 2 – Horizontal (line form)
    def test_horizontal_line(self):
        result = self._single_constraint(2, first=0, second=-1)
        cs = result["constraints"]
        assert len(cs) == 1
        assert cs[0]["type"] == "h"
        assert cs[0]["first"]["entity_id"] == "g0"

    # Type 2 – Horizontal (point-pair form)
    def test_horizontal_point_pair(self):
        result = self._single_constraint(2, first=0, second=1, first_pos=1, second_pos=2)
        cs = result["constraints"]
        assert cs[0]["type"] == "distance_y"
        assert cs[0]["value"] == 0.0

    # Type 3 – Vertical (line form)
    def test_vertical_line(self):
        result = self._single_constraint(3, first=1, second=-1)
        cs = result["constraints"]
        assert cs[0]["type"] == "v"

    # Type 3 – Vertical (point-pair form)
    def test_vertical_point_pair(self):
        result = self._single_constraint(3, first=0, second=1, first_pos=1, second_pos=2)
        cs = result["constraints"]
        assert cs[0]["type"] == "distance_x"
        assert cs[0]["value"] == 0.0

    # Type 4 – Parallel
    def test_parallel(self):
        result = self._single_constraint(4, first=0, second=1)
        cs = result["constraints"]
        assert cs[0]["type"] == "parallel"

    # Type 5 – Tangent
    def test_tangent(self):
        geom = [_line(0), _arc(1)]
        c = _constraint(5, first=0, second=1)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        assert result["constraints"][0]["type"] == "tangent"

    # Type 6 – Distance
    def test_distance(self):
        result = self._single_constraint(6, first=0, first_pos=1, second=1, second_pos=1, value=10.0)
        cs = result["constraints"]
        assert cs[0]["type"] == "distance"
        assert cs[0]["value"] == 10.0

    # Type 7 – DistanceX
    def test_distance_x(self):
        result = self._single_constraint(7, first=0, first_pos=1, second=1, second_pos=1, value=5.0)
        cs = result["constraints"]
        assert cs[0]["type"] == "distance_x"
        assert cs[0]["value"] == 5.0

    # Type 8 – DistanceY
    def test_distance_y(self):
        result = self._single_constraint(8, first=0, first_pos=1, second=1, second_pos=2, value=8.0)
        cs = result["constraints"]
        assert cs[0]["type"] == "distance_y"
        assert cs[0]["value"] == 8.0

    # Type 9 – Angle (stored in radians by FreeCAD; translated to degrees)
    def test_angle(self):
        angle_rad = math.pi / 4  # 45 degrees
        result = self._single_constraint(9, first=0, second=1, value=angle_rad)
        cs = result["constraints"]
        assert cs[0]["type"] == "angle"
        assert abs(cs[0]["value"] - 45.0) < 1e-9

    # Type 10 – Perpendicular
    def test_perpendicular(self):
        result = self._single_constraint(10, first=0, second=1)
        cs = result["constraints"]
        assert cs[0]["type"] == "perpendicular"

    # Type 11 – Radius
    def test_radius(self):
        geom = [_circle(0)]
        c = _constraint(11, first=0, value=5.0)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        cs = result["constraints"]
        assert cs[0]["type"] == "radius"
        assert cs[0]["value"] == 5.0

    # Type 12 – Equal (line pair → equal_length)
    def test_equal_length(self):
        geom = [_line(0), _line(1)]
        c = _constraint(12, first=0, second=1)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        assert result["constraints"][0]["type"] == "equal_length"

    # Type 12 – Equal (circle pair → equal_radius)
    def test_equal_radius(self):
        geom = [_circle(0), _circle(1)]
        c = _constraint(12, first=0, second=1)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        assert result["constraints"][0]["type"] == "equal_radius"

    # Type 13 – PointOnObject (line host → point_on_line)
    def test_point_on_line(self):
        geom = [_line(0), _line(1)]
        c = _constraint(13, first=0, first_pos=1, second=1)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        assert result["constraints"][0]["type"] == "point_on_line"

    # Type 13 – PointOnObject (arc host → point_on_arc)
    def test_point_on_arc(self):
        geom = [_line(0), _arc(1)]
        c = _constraint(13, first=0, first_pos=1, second=1)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        assert result["constraints"][0]["type"] == "point_on_arc"

    # Type 14 – Symmetric
    def test_symmetric(self):
        result = self._single_constraint(14, first=0, second=1, first_pos=1, second_pos=2)
        cs = result["constraints"]
        assert cs[0]["type"] == "symmetric"

    # Type 17 – Block
    def test_block(self):
        result = self._single_constraint(17, first=0)
        cs = result["constraints"]
        assert cs[0]["type"] == "block"

    # Type 18 – Diameter
    def test_diameter(self):
        geom = [_circle(0)]
        c = _constraint(18, first=0, value=10.0)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        cs = result["constraints"]
        assert cs[0]["type"] == "diameter"
        assert cs[0]["value"] == 10.0


# ---------------------------------------------------------------------------
# Drop-with-warning paths
# ---------------------------------------------------------------------------

class TestDropWithWarning:
    """Types 15 (InternalAlignment), 16 (SnellsLaw), 19 (Weight) are dropped."""

    def _dropped(self, type_int, **kwargs):
        geom = [_line(0), _line(1)]
        c = _constraint(type_int, **kwargs)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        return translate_sketch(obj)

    def test_internal_alignment_dropped(self):
        result = self._dropped(15, first=0, second=1)
        assert result["constraints"] == []
        assert any("InternalAlignment" in w for w in result["warnings"])

    def test_snells_law_dropped(self):
        result = self._dropped(16, first=0, second=1)
        assert result["constraints"] == []
        assert any("Snell" in w for w in result["warnings"])

    def test_weight_dropped(self):
        result = self._dropped(19, first=0)
        assert result["constraints"] == []
        assert any("weight" in w.lower() or "Weight" in w for w in result["warnings"])

    def test_unknown_type_dropped_with_warning(self):
        """Entirely unknown numeric type is also dropped with a warning."""
        result = self._dropped(99, first=0, second=1)
        assert result["constraints"] == []
        assert len(result["warnings"]) >= 1


# ---------------------------------------------------------------------------
# External geometry reference handling
# ---------------------------------------------------------------------------

class TestExternalGeometryRefs:
    def test_external_ref_drops_constraint(self):
        """Constraints referencing external geometry (index < -3) are dropped."""
        geom = [_line(0)]
        # -5 is an external geometry index
        c = _constraint(5, first=0, second=-5)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        assert result["constraints"] == []
        assert any("external" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# Multi-constraint sketch
# ---------------------------------------------------------------------------

class TestMultiConstraint:
    def test_mixed_constraints_partial_drop(self):
        """A sketch with a mix of valid + dropped constraints."""
        geom = [_line(0), _line(1)]
        constraints = [
            _constraint(2, first=0),            # Horizontal — kept
            _constraint(16, first=0, second=1), # SnellsLaw — dropped
            _constraint(6, first=0, second=1, first_pos=1, second_pos=1, value=20.0),  # Distance — kept
        ]
        obj = _make_sketch_obj(geometry=geom, constraints=constraints)
        result = translate_sketch(obj)
        assert len(result["constraints"]) == 2
        assert len(result["warnings"]) == 1
        assert any("Snell" in w for w in result["warnings"])

    def test_all_valid_no_warnings(self):
        geom = [_line(0), _line(1)]
        constraints = [
            _constraint(2, first=0),
            _constraint(4, first=0, second=1),
        ]
        obj = _make_sketch_obj(geometry=geom, constraints=constraints)
        result = translate_sketch(obj)
        assert len(result["constraints"]) == 2
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Entity ref vertex mapping
# ---------------------------------------------------------------------------

class TestEntityRefVertices:
    def test_start_vertex(self):
        geom = [_line(0), _line(1)]
        c = _constraint(1, first=0, second=1, first_pos=1, second_pos=2)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        cs = result["constraints"][0]
        assert cs["first"]["vertex"] == "start"
        assert cs["second"]["vertex"] == "end"

    def test_center_vertex(self):
        geom = [_line(0), _circle(1)]
        c = _constraint(1, first=0, second=1, first_pos=1, second_pos=3)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        cs = result["constraints"][0]
        assert cs["second"]["vertex"] == "center"

    def test_no_vertex_when_pos_zero(self):
        geom = [_line(0), _line(1)]
        c = _constraint(4, first=0, second=1, first_pos=0, second_pos=0)
        obj = _make_sketch_obj(geometry=geom, constraints=[c])
        result = translate_sketch(obj)
        cs = result["constraints"][0]
        assert "vertex" not in cs["first"]
        assert "vertex" not in cs["second"]
