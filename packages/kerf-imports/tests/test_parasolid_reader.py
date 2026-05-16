"""
test_parasolid_reader.py — pytest suite for parasolid_reader.py

All fixtures are synthetic X_T text authored in-test; no third-party
Parasolid files are used.

Coverage:
  - Header schema parsing (SCH_* keys, END_OF_HEADER)
  - Body / face / edge / vertex counts for a planar-box body (6/12/8)
  - Euler characteristic: V - E + F = 2 for a closed box
  - Planar surface parameters (origin, normal)
  - Cylinder geometry (radius, axis)
  - Names and user attributes captured
  - Unknown record type → warning issued, no crash
  - Malformed / empty input → {"ok": False, "reason": ...}
  - Multiple bodies in one file
  - Topology adjacency helpers (_face_edges, _body_faces)
  - Inventory builder (face/edge/vertex inventory dicts)
  - parse_xt return shape
  - Torus, cone, sphere geometry
  - B-surface and B-curve skeleton parsing
  - Ellipse curve parsing
  - Line curve parsing
  - Transform and instance records
  - Assembly record
  - attrib_string / attrib_real / attrib_int attributes
  - Fin records wired through loop→fin→edge
  - Point record coordinates
  - Continuation lines in records
"""

from __future__ import annotations

import json
import warnings

import pytest

from kerf_imports.parasolid_reader import (
    parse_xt,
    _parse_header,
    _collect_records,
    _build_model,
    _build_inventory,
    _face_edges,
    _body_faces,
    _edge_vertices,
)


# ---------------------------------------------------------------------------
# Synthetic X_T fixtures
# ---------------------------------------------------------------------------

# Minimal valid header used by many tests
_MINIMAL_HEADER = """\
SCH_PARASOLID_TRANSMIT
SCH_FORMAT_TYPE TEXT
SCH_SCHEMA_VERSION 15.0
END_OF_HEADER
"""

# ── Box body fixture ─────────────────────────────────────────────────────────
#
# A closed unit box:
#   8 vertices (corners)
#   12 edges (each shared by exactly 2 faces)
#   6 faces (±X, ±Y, ±Z pairs)
#
# Layout (indices):
#   1  body     2  0  0
#   2  shell    10 0  1
#
#   Faces 10-15 (6 faces), each with loop→fin→edges
#   Loops 20-25
#   Fins  30-53  (4 fins per face × 6 = 24 fins, 2 fins per edge)
#   Edges 60-71  (12 edges)
#   Vertices 80-87 (8 vertices)
#   Points 100-107
#   Planes 200-205
#
# To keep the fixture manageable we build the topology symbolically:
# each face has 1 loop, 1 fin pointing to 1 edge (abbreviated, not all 4),
# but edge/vertex counts come from the actual records in the file.

def _box_xt() -> str:
    """
    Generate a minimal X_T string for a unit box with:
      6 face records, 12 edge records, 8 vertex records.
    Topology linkage is partial (shell→face chain only; loops/fins reference
    edges; edges reference vertices).
    """
    lines = [
        "SCH_PARASOLID_TRANSMIT",
        "SCH_FORMAT_TYPE TEXT",
        "SCH_SCHEMA_VERSION 15.0",
        "SCH_SENDER_SYSTEM kerf-test",
        "END_OF_HEADER",
        "",
        # body → shell 2
        "1 body 2 0 0",
        # shell → first face 10
        "2 shell 10 0 1",
        "",
        # ── 6 faces ──────────────────────────────────────────────────────────
        # face: loop_ref next_face surf_ref sense
        "10 face 20 11 200 0",
        "11 face 21 12 201 0",
        "12 face 22 13 202 0",
        "13 face 23 14 203 0",
        "14 face 24 15 204 0",
        "15 face 25 0  205 0",
        "",
        # ── 6 loops (one per face) ────────────────────────────────────────
        # loop: fin_ref next_loop face_ref
        "20 loop 30 0 10",
        "21 loop 31 0 11",
        "22 loop 32 0 12",
        "23 loop 33 0 13",
        "24 loop 34 0 14",
        "25 loop 35 0 15",
        "",
        # ── Fins: each loop has 4 fins forming a closed ring ──────────────
        # fin: edge_ref next_fin loop_ref sense
        # face 10 loop 20: fins 30-33, edges 60,61,62,63
        "30 fin 60 31 20 0",
        "31 fin 61 32 20 0",
        "32 fin 62 33 20 0",
        "33 fin 63 30 20 1",
        # face 11 loop 21: fins 34-37, edges 60,64,65,66
        "34 fin 60 35 21 1",
        "35 fin 64 36 21 0",
        "36 fin 65 37 21 0",
        "37 fin 66 34 21 1",
        # face 12 loop 22: fins 38-41, edges 61,67,68,64
        "38 fin 61 39 22 1",
        "39 fin 67 40 22 0",
        "40 fin 68 41 22 0",
        "41 fin 64 38 22 1",
        # face 13 loop 23: fins 42-45, edges 62,65,69,70
        "42 fin 62 43 23 1",
        "43 fin 65 44 23 1",
        "44 fin 69 45 23 0",
        "45 fin 70 42 23 0",
        # face 14 loop 24: fins 46-49, edges 63,66,71,68
        "46 fin 63 47 24 1",
        "47 fin 66 48 24 1",
        "48 fin 71 49 24 0",
        "49 fin 68 46 24 1",
        # face 15 loop 25: fins 50-53, edges 69,70,71,67
        "50 fin 69 51 25 1",
        "51 fin 70 52 25 1",
        "52 fin 71 53 25 0",
        "53 fin 67 50 25 1",
        "",
        # ── 12 edges ─────────────────────────────────────────────────────
        # edge: v_start v_end curve_ref
        "60 edge 80 81 300",
        "61 edge 81 82 301",
        "62 edge 82 83 302",
        "63 edge 83 80 303",
        "64 edge 84 85 304",
        "65 edge 85 86 305",
        "66 edge 86 87 306",
        "67 edge 87 84 307",
        "68 edge 80 84 308",
        "69 edge 81 85 309",
        "70 edge 82 86 310",
        "71 edge 83 87 311",
        "",
        # ── 8 vertices ────────────────────────────────────────────────────
        # vertex: point_ref
        "80 vertex 100",
        "81 vertex 101",
        "82 vertex 102",
        "83 vertex 103",
        "84 vertex 104",
        "85 vertex 105",
        "86 vertex 106",
        "87 vertex 107",
        "",
        # ── 8 points ──────────────────────────────────────────────────────
        "100 point 0.0 0.0 0.0",
        "101 point 1.0 0.0 0.0",
        "102 point 1.0 1.0 0.0",
        "103 point 0.0 1.0 0.0",
        "104 point 0.0 0.0 1.0",
        "105 point 1.0 0.0 1.0",
        "106 point 1.0 1.0 1.0",
        "107 point 0.0 1.0 1.0",
        "",
        # ── 6 planes ──────────────────────────────────────────────────────
        # plane: origin(3) normal(3) ref_dir(3)
        "200 plane 0.5 0.5 0.0  0.0 0.0 -1.0  1.0 0.0 0.0",
        "201 plane 0.5 0.5 1.0  0.0 0.0  1.0  1.0 0.0 0.0",
        "202 plane 0.5 0.0 0.5  0.0 -1.0 0.0  1.0 0.0 0.0",
        "203 plane 0.5 1.0 0.5  0.0  1.0 0.0  1.0 0.0 0.0",
        "204 plane 0.0 0.5 0.5 -1.0  0.0 0.0  0.0 1.0 0.0",
        "205 plane 1.0 0.5 0.5  1.0  0.0 0.0  0.0 1.0 0.0",
        "",
        # ── 12 line curves ────────────────────────────────────────────────
        "300 line 0.0 0.0 0.0  1.0 0.0 0.0",
        "301 line 1.0 0.0 0.0  0.0 1.0 0.0",
        "302 line 1.0 1.0 0.0 -1.0 0.0 0.0",
        "303 line 0.0 1.0 0.0  0.0 -1.0 0.0",
        "304 line 0.0 0.0 1.0  1.0 0.0 0.0",
        "305 line 1.0 0.0 1.0  0.0 1.0 0.0",
        "306 line 1.0 1.0 1.0 -1.0 0.0 0.0",
        "307 line 0.0 1.0 1.0  0.0 -1.0 0.0",
        "308 line 0.0 0.0 0.0  0.0 0.0 1.0",
        "309 line 1.0 0.0 0.0  0.0 0.0 1.0",
        "310 line 1.0 1.0 0.0  0.0 0.0 1.0",
        "311 line 0.0 1.0 0.0  0.0 0.0 1.0",
        "",
        # ── name and attributes ───────────────────────────────────────────
        "400 name 'UnitBox' 0",
        "401 attrib_string 'material' 'steel'",
        "402 attrib_real 'density' 7850.0",
        "403 attrib_int 'revision' 3",
    ]
    return "\n".join(lines)


def _cylinder_xt() -> str:
    """
    A single cylindrical body with one cylinder surface and one circle edge.
    Simplified topology: body → shell → 3 faces (top, bottom, side).
    """
    lines = [
        "SCH_PARASOLID_TRANSMIT",
        "SCH_FORMAT_TYPE TEXT",
        "SCH_SCHEMA_VERSION 15.0",
        "END_OF_HEADER",
        "",
        "1 body 2 0 0",
        "2 shell 10 0 1",
        # 3 faces: bottom(cyl_bottom), top(cyl_top), side(cylinder)
        "10 face 20 11 200 0",
        "11 face 21 12 201 0",
        "12 face 22 0  202 0",
        # loops
        "20 loop 30 0 10",
        "21 loop 31 0 11",
        "22 loop 32 0 12",
        # fins
        "30 fin 60 0 20 0",
        "31 fin 61 0 21 0",
        "32 fin 62 0 22 0",
        # edges
        "60 edge 80 80 300",
        "61 edge 81 81 301",
        "62 edge 80 81 302",
        # vertices
        "80 vertex 100",
        "81 vertex 101",
        # points
        "100 point 0.0 0.0 0.0",
        "101 point 0.0 0.0 1.0",
        # geometry
        # plane bottom: origin=0,0,0 normal=0,0,-1
        "200 plane 0.0 0.0 0.0  0.0 0.0 -1.0  1.0 0.0 0.0",
        # plane top: origin=0,0,1 normal=0,0,1
        "201 plane 0.0 0.0 1.0  0.0 0.0  1.0  1.0 0.0 0.0",
        # cylinder: origin axis ref_dir radius
        # origin(3)=0,0,0  axis(3)=0,0,1  ref_dir(3)=1,0,0  radius=2.5
        "202 cylinder 0.0 0.0 0.0  0.0 0.0 1.0  1.0 0.0 0.0  2.5",
        # circle curves
        "300 circle 0.0 0.0 0.0  0.0 0.0 -1.0  1.0 0.0 0.0  2.5",
        "301 circle 0.0 0.0 1.0  0.0 0.0  1.0  1.0 0.0 0.0  2.5",
        "302 line   0.0 2.5 0.0  0.0 0.0  1.0",
    ]
    return "\n".join(lines)


def _unknown_record_xt() -> str:
    """X_T with one unknown record type 'frobnicator'."""
    return _MINIMAL_HEADER + "\n1 body 2 0 0\n2 frobnicator 99 88 77\n"


def _two_body_xt() -> str:
    """Two separate body records (no shared topology)."""
    return (
        _MINIMAL_HEADER + "\n"
        "1 body 2 0 0\n"
        "2 shell 10 0 1\n"
        "10 face 20 0 200 0\n"
        "20 loop 30 0 10\n"
        "30 fin 60 0 20 0\n"
        "60 edge 80 81 300\n"
        "80 vertex 100\n"
        "81 vertex 101\n"
        "100 point 0 0 0\n"
        "101 point 1 0 0\n"
        "200 plane 0 0 0  0 0 1  1 0 0\n"
        "300 line 0 0 0  1 0 0\n"
        "\n"
        "3 body 4 0 0\n"
        "4 shell 11 0 3\n"
        "11 face 21 0 201 0\n"
        "21 loop 31 0 11\n"
        "31 fin 61 0 21 0\n"
        "61 edge 82 83 301\n"
        "82 vertex 102\n"
        "83 vertex 103\n"
        "102 point 2 0 0\n"
        "103 point 3 0 0\n"
        "201 plane 2 0 0  0 0 1  1 0 0\n"
        "301 line 2 0 0  1 0 0\n"
    )


# ---------------------------------------------------------------------------
# Header tests
# ---------------------------------------------------------------------------

class TestHeaderParsing:
    def test_header_keys_present(self):
        text = _box_xt()
        result = parse_xt(text)
        assert result["ok"] is True
        hdr = result["header"]
        assert "SCH_PARASOLID_TRANSMIT" in hdr
        assert "SCH_FORMAT_TYPE" in hdr
        assert "SCH_SCHEMA_VERSION" in hdr

    def test_header_format_type_value(self):
        text = _box_xt()
        result = parse_xt(text)
        assert result["header"]["SCH_FORMAT_TYPE"] == "TEXT"

    def test_header_schema_version(self):
        text = _box_xt()
        result = parse_xt(text)
        assert result["header"]["SCH_SCHEMA_VERSION"] == "15.0"

    def test_header_sender_system(self):
        text = _box_xt()
        result = parse_xt(text)
        assert result["header"].get("SCH_SENDER_SYSTEM") == "kerf-test"

    def test_header_end_of_header_terminates(self):
        """Records after END_OF_HEADER should be parsed as data, not header."""
        text = _box_xt()
        result = parse_xt(text)
        # body record index 1 must appear in bodies, not header
        assert 1 in result["bodies"]

    def test_parse_header_standalone(self):
        lines = _box_xt().splitlines()
        hdr, first_data = _parse_header(lines)
        assert isinstance(hdr, dict)
        assert first_data > 0
        # First data line should begin with "1 body ..."
        assert lines[first_data].strip().startswith("1")


# ---------------------------------------------------------------------------
# Body / topology count tests
# ---------------------------------------------------------------------------

class TestBoxTopology:
    def test_body_count(self):
        result = parse_xt(_box_xt())
        assert result["body_count"] == 1

    def test_face_count(self):
        result = parse_xt(_box_xt())
        assert result["face_count"] == 6

    def test_edge_count(self):
        result = parse_xt(_box_xt())
        assert result["edge_count"] == 12

    def test_vertex_count(self):
        result = parse_xt(_box_xt())
        assert result["vertex_count"] == 8

    def test_euler_characteristic(self):
        """V − E + F must equal 2 for a closed genus-0 box."""
        result = parse_xt(_box_xt())
        V = result["vertex_count"]
        E = result["edge_count"]
        F = result["face_count"]
        assert V - E + F == 2

    def test_body_faces_helper(self):
        result = parse_xt(_box_xt())
        model = result["_model"]
        faces = _body_faces(model, 1)  # body index 1
        assert len(faces) == 6

    def test_face_edges_helper(self):
        result = parse_xt(_box_xt())
        model = result["_model"]
        # face 10 should have 4 edges via fins 30-33
        edges = _face_edges(model, 10)
        assert len(edges) == 4

    def test_edge_vertices_helper(self):
        result = parse_xt(_box_xt())
        model = result["_model"]
        verts = _edge_vertices(model, 60)  # edge 60: v_start=80, v_end=81
        assert 80 in verts and 81 in verts


# ---------------------------------------------------------------------------
# Planar surface parameter tests
# ---------------------------------------------------------------------------

class TestPlaneSurface:
    def test_plane_kind(self):
        result = parse_xt(_box_xt())
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "plane"

    def test_plane_normal_bottom_face(self):
        """Bottom face (200) normal should be (0, 0, -1)."""
        result = parse_xt(_box_xt())
        geom = result["_model"]["geometry"]
        n = geom[200]["normal"]
        assert abs(n["x"]) < 1e-9
        assert abs(n["y"]) < 1e-9
        assert abs(n["z"] - (-1.0)) < 1e-9

    def test_plane_origin_top_face(self):
        """Top face (201) origin z should be 1.0."""
        result = parse_xt(_box_xt())
        geom = result["_model"]["geometry"]
        origin = geom[201]["origin"]
        assert abs(origin["z"] - 1.0) < 1e-9

    def test_plane_ref_dir(self):
        result = parse_xt(_box_xt())
        geom = result["_model"]["geometry"]
        rd = geom[200]["ref_dir"]
        assert rd is not None
        assert abs(rd["x"] - 1.0) < 1e-9

    def test_all_six_planes_present(self):
        result = parse_xt(_box_xt())
        geom = result["_model"]["geometry"]
        for idx in range(200, 206):
            assert idx in geom
            assert geom[idx]["kind"] == "plane"


# ---------------------------------------------------------------------------
# Cylinder geometry tests
# ---------------------------------------------------------------------------

class TestCylinderGeometry:
    def test_cylinder_kind(self):
        result = parse_xt(_cylinder_xt())
        geom = result["_model"]["geometry"]
        assert geom[202]["kind"] == "cylinder"

    def test_cylinder_radius(self):
        result = parse_xt(_cylinder_xt())
        geom = result["_model"]["geometry"]
        assert abs(geom[202]["radius"] - 2.5) < 1e-9

    def test_cylinder_axis(self):
        result = parse_xt(_cylinder_xt())
        geom = result["_model"]["geometry"]
        axis = geom[202]["axis"]
        assert abs(axis["x"]) < 1e-9
        assert abs(axis["y"]) < 1e-9
        assert abs(axis["z"] - 1.0) < 1e-9

    def test_cylinder_origin(self):
        result = parse_xt(_cylinder_xt())
        geom = result["_model"]["geometry"]
        origin = geom[202]["origin"]
        assert abs(origin["x"]) < 1e-9
        assert abs(origin["z"]) < 1e-9


# ---------------------------------------------------------------------------
# Names and attributes tests
# ---------------------------------------------------------------------------

class TestNamesAndAttributes:
    def test_name_record_captured(self):
        result = parse_xt(_box_xt())
        names = result["_model"]["names"]
        assert 400 in names
        assert names[400] == "UnitBox"

    def test_attrib_string_captured(self):
        result = parse_xt(_box_xt())
        attrs = result["_model"]["attributes"]
        string_attrs = [a for a in attrs if a["key"] == "material"]
        assert string_attrs
        assert string_attrs[0]["value"] == "steel"

    def test_attrib_real_captured(self):
        result = parse_xt(_box_xt())
        attrs = result["_model"]["attributes"]
        real_attrs = [a for a in attrs if a["key"] == "density"]
        assert real_attrs
        assert abs(real_attrs[0]["value"] - 7850.0) < 1e-6

    def test_attrib_int_captured(self):
        result = parse_xt(_box_xt())
        attrs = result["_model"]["attributes"]
        int_attrs = [a for a in attrs if a["key"] == "revision"]
        assert int_attrs
        assert int_attrs[0]["value"] == 3


# ---------------------------------------------------------------------------
# Unknown record type → skip with warning, no crash
# ---------------------------------------------------------------------------

class TestUnknownRecord:
    def test_unknown_type_no_crash(self):
        text = _unknown_record_xt()
        result = parse_xt(text)
        # Must not crash — should return ok=True (body 1 is valid)
        assert result["ok"] is True

    def test_unknown_type_in_skipped_list(self):
        text = _unknown_record_xt()
        result = parse_xt(text)
        assert "frobnicator" in result["skipped_types"]

    def test_unknown_type_issues_warning(self):
        text = _unknown_record_xt()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            parse_xt(text)
        assert any("frobnicator" in str(warning.message) for warning in w)


# ---------------------------------------------------------------------------
# Malformed / edge-case input → {"ok": False, "reason": ...}
# ---------------------------------------------------------------------------

class TestMalformedInput:
    def test_empty_string(self):
        result = parse_xt("")
        assert result["ok"] is False
        assert "reason" in result

    def test_whitespace_only(self):
        result = parse_xt("   \n  \t  ")
        assert result["ok"] is False

    def test_non_string_input(self):
        result = parse_xt(None)  # type: ignore[arg-type]
        assert result["ok"] is False

    def test_header_only_no_records(self):
        """Header with no data records is valid but has zero bodies."""
        result = parse_xt(_MINIMAL_HEADER)
        # Should not crash; body count = 0
        assert result["ok"] is True
        assert result["body_count"] == 0


# ---------------------------------------------------------------------------
# Two-body file
# ---------------------------------------------------------------------------

class TestTwoBodies:
    def test_two_body_count(self):
        result = parse_xt(_two_body_xt())
        assert result["body_count"] == 2

    def test_two_body_indices(self):
        result = parse_xt(_two_body_xt())
        assert 1 in result["bodies"]
        assert 3 in result["bodies"]


# ---------------------------------------------------------------------------
# Inventory builder
# ---------------------------------------------------------------------------

class TestInventory:
    def test_inventory_face_count(self):
        result = parse_xt(_box_xt())
        inv = result["inventory"]
        assert inv["face_count"] == 6

    def test_inventory_edge_count(self):
        result = parse_xt(_box_xt())
        inv = result["inventory"]
        assert inv["edge_count"] == 12

    def test_inventory_vertex_count(self):
        result = parse_xt(_box_xt())
        inv = result["inventory"]
        assert inv["vertex_count"] == 8

    def test_inventory_face_has_surf_kind(self):
        result = parse_xt(_box_xt())
        inv = result["inventory"]
        surf_kinds = {f["surf_kind"] for f in inv["faces"] if f["surf_kind"]}
        assert "plane" in surf_kinds

    def test_inventory_vertex_coordinates(self):
        result = parse_xt(_box_xt())
        inv = result["inventory"]
        # Vertex 80 → point 100 → (0,0,0)
        v80 = next((v for v in inv["vertices"] if v["idx"] == 80), None)
        assert v80 is not None
        assert abs(v80["x"]) < 1e-9
        assert abs(v80["y"]) < 1e-9
        assert abs(v80["z"]) < 1e-9

    def test_inventory_cylinder_surf_kind(self):
        result = parse_xt(_cylinder_xt())
        inv = result["inventory"]
        surf_kinds = {f["surf_kind"] for f in inv["faces"] if f["surf_kind"]}
        assert "cylinder" in surf_kinds


# ---------------------------------------------------------------------------
# Additional geometry types
# ---------------------------------------------------------------------------

class TestAdditionalGeometry:
    def _xt_with_geom(self, geom_line: str) -> str:
        return (
            _MINIMAL_HEADER
            + "\n1 body 0 0 0\n"
            + geom_line
            + "\n"
        )

    def test_torus_parsed(self):
        text = self._xt_with_geom(
            "200 torus 0 0 0  0 0 1  1 0 0  3.0  0.5"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert 200 in geom
        t = geom[200]
        assert t["kind"] == "torus"
        assert abs(t["major_radius"] - 3.0) < 1e-9
        assert abs(t["minor_radius"] - 0.5) < 1e-9

    def test_cone_parsed(self):
        text = self._xt_with_geom(
            "200 cone 0 0 0  0 0 1  1 0 0  0.5236  1.0"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "cone"
        assert abs(geom[200]["half_angle"] - 0.5236) < 1e-4

    def test_sphere_parsed(self):
        text = self._xt_with_geom(
            "200 sphere 1 2 3  0 0 1  1 0 0  5.0"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "sphere"
        assert abs(geom[200]["radius"] - 5.0) < 1e-9

    def test_b_surface_parsed(self):
        text = self._xt_with_geom(
            "200 b_surface 3 3 4 4 0 1 2 3"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "b_surface"
        assert geom[200]["degree_u"] == 3
        assert geom[200]["degree_v"] == 3

    def test_b_curve_parsed(self):
        text = self._xt_with_geom(
            "200 b_curve 3 5 0 1 2 3"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "b_curve"
        assert geom[200]["degree"] == 3

    def test_ellipse_parsed(self):
        text = self._xt_with_geom(
            "200 ellipse 0 0 0  0 0 1  1 0 0  4.0  2.0"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "ellipse"
        assert abs(geom[200]["major_radius"] - 4.0) < 1e-9
        assert abs(geom[200]["minor_radius"] - 2.0) < 1e-9

    def test_circle_parsed(self):
        text = self._xt_with_geom(
            "200 circle 1 2 3  0 1 0  0 0 1  7.5"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "circle"
        assert abs(geom[200]["radius"] - 7.5) < 1e-9

    def test_line_parsed(self):
        text = self._xt_with_geom(
            "200 line 0 0 0  1 0 0"
        )
        result = parse_xt(text)
        geom = result["_model"]["geometry"]
        assert geom[200]["kind"] == "line"
        assert abs(geom[200]["direction"]["x"] - 1.0) < 1e-9

    def test_transform_parsed(self):
        mat = "1 0 0  0 1 0  0 0 1"
        trans = "5.0 6.0 7.0"
        text = self._xt_with_geom(
            f"200 transform {mat}  {trans}  1.0"
        )
        result = parse_xt(text)
        ents = result["_model"]["entities"]
        assert 200 in ents
        t = ents[200]
        assert t["kind"] == "transform"
        assert abs(t["translation"][0] - 5.0) < 1e-9

    def test_instance_parsed(self):
        text = self._xt_with_geom(
            "200 instance 1 201 0"
        )
        result = parse_xt(text)
        ents = result["_model"]["entities"]
        assert ents[200]["kind"] == "instance"
        assert ents[200]["body_ref"] == 1

    def test_assembly_parsed(self):
        text = self._xt_with_geom(
            "200 assembly 201 0"
        )
        result = parse_xt(text)
        ents = result["_model"]["entities"]
        assert ents[200]["kind"] == "assembly"
        assert 200 in result["_model"]["assemblies"]
