"""
Tests for kerf_civil.landxml — LandXML 1.2 import/export round-trip.
"""
import asyncio
import math
import pytest
from kerf_civil.landxml import _NS, export_landxml, import_landxml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pts_close(a, b, tol=1e-4):
    """Check that two (x, y) or (x, y, z) tuples are within tolerance."""
    for va, vb in zip(a, b):
        assert abs(float(va) - float(vb)) < tol, f"{a!r} vs {b!r} differ"


# ---------------------------------------------------------------------------
# Alignment round-trip
# ---------------------------------------------------------------------------

class TestAlignmentRoundTrip:
    def _alignment(self):
        return {
            "name": "MainRoad",
            "desc": "Test alignment",
            "elements": [
                {"type": "Line",  "start": (100.0, 200.0), "end": (300.0, 400.0)},
                {
                    "type": "Curve",
                    "start":  (300.0, 400.0),
                    "center": (400.0, 300.0),
                    "end":    (450.0, 200.0),
                    "radius": 141.421,
                    "dir":    "CW",
                },
            ],
            "profile": {
                "elements": [
                    {"type": "PVI",       "station": 0.0,   "elevation": 10.0},
                    {"type": "ParaCurve", "station": 150.0, "elevation": 12.5, "length": 60.0},
                    {"type": "PVI",       "station": 300.0, "elevation": 15.0},
                ],
            },
        }

    def test_export_produces_xml(self):
        xml = export_landxml(alignments=[self._alignment()])
        assert "<Alignment" in xml
        assert "MainRoad" in xml

    def test_round_trip_element_count(self):
        aln = self._alignment()
        xml = export_landxml(alignments=[aln])
        result = import_landxml(xml)
        assert len(result["alignments"]) == 1
        imported = result["alignments"][0]
        assert len(imported["elements"]) == 2

    def test_round_trip_line_coords(self):
        aln = self._alignment()
        xml = export_landxml(alignments=[aln])
        result = import_landxml(xml)
        imported = result["alignments"][0]
        line = imported["elements"][0]
        assert line["type"] == "Line"
        _pts_close(line["start"], (100.0, 200.0))
        _pts_close(line["end"],   (300.0, 400.0))

    def test_round_trip_curve_coords(self):
        aln = self._alignment()
        xml = export_landxml(alignments=[aln])
        result = import_landxml(xml)
        imported = result["alignments"][0]
        curve = imported["elements"][1]
        assert curve["type"] == "Curve"
        _pts_close(curve["start"],  (300.0, 400.0))
        _pts_close(curve["center"], (400.0, 300.0))
        _pts_close(curve["end"],    (450.0, 200.0))
        assert abs(curve["radius"] - 141.421) < 0.01
        assert curve["dir"] == "CW"

    def test_round_trip_profile(self):
        aln = self._alignment()
        xml = export_landxml(alignments=[aln])
        result = import_landxml(xml)
        imported = result["alignments"][0]
        assert imported["profile"] is not None
        profile_elements = imported["profile"]["elements"]
        # PVI + ParaCurve + PVI = 3
        assert len(profile_elements) == 3
        # ParaCurve has length
        para = next(e for e in profile_elements if e["type"] == "ParaCurve")
        assert abs(para["length"] - 60.0) < 0.01

    def test_alignment_name_preserved(self):
        aln = self._alignment()
        xml = export_landxml(alignments=[aln])
        result = import_landxml(xml)
        assert result["alignments"][0]["name"] == "MainRoad"


# ---------------------------------------------------------------------------
# Surface (TIN) round-trip
# ---------------------------------------------------------------------------

class TestSurfaceRoundTrip:
    def _surface(self):
        return {
            "name": "TestTIN",
            "points": [
                (0.0, 0.0, 10.0),
                (10.0, 0.0, 11.0),
                (5.0, 10.0, 12.0),
                (15.0, 10.0, 10.5),
            ],
            "faces": [
                (1, 2, 3),
                (2, 4, 3),
            ],
        }

    def test_export_contains_surface(self):
        xml = export_landxml(surfaces=[self._surface()])
        assert "<Surface" in xml
        assert "TestTIN" in xml

    def test_round_trip_point_count(self):
        surf = self._surface()
        xml = export_landxml(surfaces=[surf])
        result = import_landxml(xml)
        assert len(result["surfaces"]) == 1
        imported = result["surfaces"][0]
        assert len(imported["points"]) == 4

    def test_round_trip_point_coords(self):
        surf = self._surface()
        xml = export_landxml(surfaces=[surf])
        result = import_landxml(xml)
        pts = result["surfaces"][0]["points"]
        _pts_close(pts[0], (0.0, 0.0, 10.0))
        _pts_close(pts[1], (10.0, 0.0, 11.0))
        _pts_close(pts[2], (5.0, 10.0, 12.0))

    def test_round_trip_faces(self):
        surf = self._surface()
        xml = export_landxml(surfaces=[surf])
        result = import_landxml(xml)
        faces = result["surfaces"][0]["faces"]
        assert len(faces) == 2
        assert set(faces[0]) == {1, 2, 3}

    def test_surface_name_preserved(self):
        surf = self._surface()
        xml = export_landxml(surfaces=[surf])
        result = import_landxml(xml)
        assert result["surfaces"][0]["name"] == "TestTIN"


# ---------------------------------------------------------------------------
# Parcel round-trip
# ---------------------------------------------------------------------------

class TestParcelRoundTrip:
    def _parcel(self):
        return {
            "name": "Lot42",
            "lines": [
                {"start": (0.0, 0.0),   "end": (20.0, 0.0)},
                {"start": (20.0, 0.0),  "end": (20.0, 15.0)},
                {"start": (20.0, 15.0), "end": (0.0, 15.0)},
                {"start": (0.0, 15.0),  "end": (0.0, 0.0)},
            ],
        }

    def test_export_contains_parcel(self):
        xml = export_landxml(parcels=[self._parcel()])
        assert "<Parcel" in xml
        assert "Lot42" in xml

    def test_round_trip_line_count(self):
        parcel = self._parcel()
        xml = export_landxml(parcels=[parcel])
        result = import_landxml(xml)
        assert len(result["parcels"]) == 1
        assert len(result["parcels"][0]["lines"]) == 4

    def test_round_trip_coords(self):
        parcel = self._parcel()
        xml = export_landxml(parcels=[parcel])
        result = import_landxml(xml)
        line0 = result["parcels"][0]["lines"][0]
        _pts_close(line0["start"], (0.0, 0.0))
        _pts_close(line0["end"],   (20.0, 0.0))


# ---------------------------------------------------------------------------
# Combined round-trip
# ---------------------------------------------------------------------------

def test_combined_export_import():
    """All three element types in one file."""
    aln = {
        "name": "Road1",
        "elements": [{"type": "Line", "start": (0.0, 0.0), "end": (100.0, 0.0)}],
    }
    surf = {
        "name": "DTM",
        "points": [(0, 0, 0), (50, 0, 1), (25, 50, 2)],
        "faces": [(1, 2, 3)],
    }
    parcel = {
        "name": "Lot1",
        "lines": [{"start": (0.0, 0.0), "end": (10.0, 0.0)}],
    }
    xml = export_landxml(alignments=[aln], surfaces=[surf], parcels=[parcel])
    result = import_landxml(xml)
    assert len(result["alignments"]) == 1
    assert len(result["surfaces"]) == 1
    assert len(result["parcels"]) == 1


def test_empty_export_is_valid_xml():
    xml = export_landxml()
    result = import_landxml(xml)
    assert result["alignments"] == []
    assert result["surfaces"] == []
    assert result["parcels"] == []


# ---------------------------------------------------------------------------
# LLM tool handler
# ---------------------------------------------------------------------------

def test_tool_import_handler():
    from kerf_civil.tools_hydraulics import run_civil_landxml_import
    from kerf_civil._compat import ProjectCtx
    import json

    aln = {"name": "A1", "elements": [{"type": "Line", "start": (0.0, 0.0), "end": (1.0, 1.0)}]}
    xml = export_landxml(alignments=[aln])
    result = asyncio.run(run_civil_landxml_import({"xml_str": xml}, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert len(data["alignments"]) == 1


def test_tool_export_handler():
    from kerf_civil.tools_hydraulics import run_civil_landxml_export
    from kerf_civil._compat import ProjectCtx
    import json

    params = {
        "alignments": [{"name": "A1", "elements": [{"type": "Line", "start": [0.0, 0.0], "end": [1.0, 1.0]}]}],
    }
    result = asyncio.run(run_civil_landxml_export(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert "<LandXML" in data["xml_str"]


# ---------------------------------------------------------------------------
# Namespace independence
# ---------------------------------------------------------------------------

class TestNamespaceIsNotGlobal:
    """The writer must not depend on ElementTree's process-global prefix map.

    It used to call ET.register_namespace("", _NS) at import time to get
    xmlns="..." on the root instead of ns0: on every element. That map is
    global, and Kerf has three writers that each want the empty prefix for a
    different namespace — this one, kerf-cad-core's 3MF writer, and kerf-plc's
    PLCopen writer. Whoever registered last won.

    So exporting a 3MF and then a LandXML in the same process emitted LandXML
    with ns0: throughout: still well-formed, but not the shape consumers expect,
    and varying with whatever the user happened to export earlier. In the test
    suite it showed up as four landxml failures that passed in isolation.
    """

    def _alignment(self):
        return {
            "name": "MainRoad",
            "elements": [{"type": "Line", "start": (0.0, 0.0), "end": (1.0, 1.0)}],
        }

    def test_export_is_unprefixed_after_another_writer_claims_the_empty_prefix(self):
        import xml.etree.ElementTree as ET

        ET.register_namespace("", "http://example.invalid/some-other-format")

        xml = export_landxml(alignments=[self._alignment()])

        assert "<LandXML" in xml
        assert "<Alignment" in xml
        assert "ns0:" not in xml

    def test_the_namespace_is_still_declared(self):
        # Unprefixed is only correct if the default namespace is declared —
        # otherwise the document says these elements are in no namespace at all.
        xml = export_landxml(alignments=[self._alignment()])
        assert f'xmlns="{_NS}"' in xml

    def test_round_trip_survives_a_stolen_prefix(self):
        import xml.etree.ElementTree as ET

        ET.register_namespace("", "http://example.invalid/some-other-format")

        xml = export_landxml(alignments=[self._alignment()])
        result = import_landxml(xml)

        assert len(result["alignments"]) == 1
        assert result["alignments"][0]["name"] == "MainRoad"
