"""
test_iges_reader_writer.py

Tests for kerf_imports.iges_reader and kerf_imports.iges_writer.
All oracle values are derived from ASME Y14.26M / IGES 5.3 specification.

Coverage:
  1. iges_reader: valid IGES file section identification
  2. iges_reader: entity parsing from D-section
  3. iges_reader: global section (units, product ID)
  4. iges_reader: entity counts
  5. iges_reader: invalid / empty file graceful failure
  6. iges_writer: produces valid IGES section markers
  7. iges_writer: Line entity (Type 110) produced
  8. iges_writer: NURBS Curve entity (Type 126) produced
  9. iges_writer: NURBS Surface entity (Type 128) produced
 10. iges_writer: uniform clamped knot vector oracle
 11. round-trip: write → read gives consistent entity counts
 12. iges_reader: to_dict schema completeness
"""

import math
import pytest

from kerf_imports.iges_writer import (
    IGESLine,
    IGESModel,
    IGESNURBSCurve,
    IGESNURBSSurface,
    IGESPoint,
    _uniform_clamped_knots,
    write_iges,
    write_iges_bytes,
)
from kerf_imports.iges_reader import (
    parse_iges,
    IGESResult,
    _SECTION_D,
    _SECTION_G,
    _SECTION_P,
    _SECTION_S,
    _SECTION_T,
)


# ---------------------------------------------------------------------------
# Minimal synthetic IGES files for reader tests
# ---------------------------------------------------------------------------

def _make_minimal_iges_header() -> str:
    """
    Minimal IGES text with Start + Global + Terminate sections only.
    No entities (no D/P sections). Used to test section parsing.
    """
    lines = [
        # S-section (col 73 = 'S', col 74-80 = seq 1)
        f"{'Kerf test IGES file':<72}S{1:7d}",
        # G-section: minimal global params
        f"{',;,4Htest,8Htest.igs,4HKerf,12HKerf v1.0.0,':<72}G{1:7d}",
        # T-section
        f"{'S      1G      1D      0P      0':<72}T{1:7d}",
    ]
    return "\n".join(lines)


def _make_iges_with_line() -> str:
    """IGES file with a single Line entity (Type 110)."""
    lines = [
        # Start
        f"{'Test IGES with Line':<72}S{1:7d}",
        # Global
        f"{',;,4Htest,8Htest.igs,4HKerf,12HKerf v1.0.0,,,,,,,,,,2,2H':<72}G{1:7d}",
        # Directory - line 1: entity type=110, param_data_seq=1
        f"{'     110       1       0       0       0       0       000000000':<72}D{1:7d}",
        # Directory - line 2: entity type=110 (repeated)
        f"{'     110       0       0       1       0                        ':<72}D{2:7d}",
        # Parameter: Type 110, X1,Y1,Z1, X2,Y2,Z2
        f"{'110,0.0,0.0,0.0,10.0,20.0,30.0;':<64}{1:8d}P{1:7d}",
        # Terminate
        f"{'S      1G      1D      2P      1':<72}T{1:7d}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. Section identification
# ---------------------------------------------------------------------------

class TestIGESReaderSections:
    def test_valid_file_ok_true(self):
        text = _make_minimal_iges_header()
        result = parse_iges(text)
        assert result.ok is True

    def test_empty_file_ok_false(self):
        result = parse_iges(b"")
        assert result.ok is False
        assert result.warnings

    def test_invalid_content_ok_false(self):
        result = parse_iges("This is not an IGES file at all.")
        assert result.ok is False
        assert "Not a valid IGES" in result.warnings[0]

    def test_accepts_bytes(self):
        text = _make_minimal_iges_header()
        result = parse_iges(text.encode("ascii"))
        assert result.ok is True

    def test_accepts_str(self):
        result = parse_iges(_make_minimal_iges_header())
        assert result.ok is True


# ---------------------------------------------------------------------------
# 2. Entity parsing from D-section
# ---------------------------------------------------------------------------

class TestIGESReaderEntities:
    def test_line_entity_parsed(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        assert result.ok is True
        assert len(result.entities) == 1
        entity = result.entities[0]
        assert entity.entity_type == 110
        assert entity.entity_name == "Line"

    def test_entity_sequence_number(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        assert result.entities[0].sequence_number == 1

    def test_entity_param_data_seq(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        assert result.entities[0].parameter_data_seq == 1

    def test_entity_params_parsed(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        ent = result.entities[0]
        # First param should be entity type 110
        assert ent.params[0] == 110
        # X1=0, Y1=0, Z1=0 should be in params
        assert 0.0 in ent.params or 0 in ent.params


# ---------------------------------------------------------------------------
# 3. Global section
# ---------------------------------------------------------------------------

class TestIGESReaderGlobal:
    def test_units_mm(self):
        # Build IGES with MM units (unit_flag=2)
        g_line = (
            ",;,4Htest,8Htest.igs,4HKerf,12HKerf v1.0.0,32,38,309,15,307,"
            "4Htest,1.0,2,2HMM,1,0.001,15H20260101.000000,1E-6,1E6,4HKerf,0H,11,0;"
        )
        lines = [
            f"{'Test':<72}S{1:7d}",
            f"{g_line[:72]:<72}G{1:7d}",
            f"{'S      1G      1D      0P      0':<72}T{1:7d}",
        ]
        result = parse_iges("\n".join(lines))
        assert result.ok is True
        # Unit flag 2 = MM (stored as MILLIMETERS in the name lookup)
        assert result.global_section.units_flag == 2
        # units_name should contain "MM" or "MILLIMETER"
        assert "M" in result.global_section.units_name.upper()

    def test_start_text_captured(self):
        text = _make_minimal_iges_header()
        result = parse_iges(text)
        assert "Kerf test IGES file" in result.start_text

    def test_global_section_defaults(self):
        text = _make_minimal_iges_header()
        result = parse_iges(text)
        # default unit_flag = 1 (INCHES) if not specified
        assert result.global_section is not None


# ---------------------------------------------------------------------------
# 4. Entity counts
# ---------------------------------------------------------------------------

class TestIGESReaderEntityCounts:
    def test_entity_counts_dict(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        assert "Line" in result.entity_counts
        assert result.entity_counts["Line"] == 1

    def test_empty_entity_counts(self):
        text = _make_minimal_iges_header()
        result = parse_iges(text)
        assert isinstance(result.entity_counts, dict)
        assert len(result.entity_counts) == 0

    def test_to_dict_total_entities(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        d = result.to_dict()
        assert d["total_entities"] == 1

    def test_to_dict_schema(self):
        text = _make_iges_with_line()
        result = parse_iges(text)
        d = result.to_dict()
        assert "ok" in d
        assert "units" in d
        assert "product_id" in d
        assert "total_entities" in d
        assert "entity_counts" in d
        assert "nurbs_curves" in d
        assert "nurbs_surfaces" in d
        assert "brep_bodies" in d
        assert "warnings" in d


# ---------------------------------------------------------------------------
# 5. IGES writer: section markers
# ---------------------------------------------------------------------------

class TestIGESWriterSections:
    def _simple_model(self) -> IGESModel:
        m = IGESModel(product_id="test_part", units="MM")
        m.lines.append(IGESLine(
            start=IGESPoint(0.0, 0.0, 0.0),
            end=IGESPoint(10.0, 0.0, 0.0),
            label="edge",
        ))
        return m

    def test_output_is_string(self):
        text = write_iges(self._simple_model())
        assert isinstance(text, str)

    def test_output_is_bytes(self):
        b = write_iges_bytes(self._simple_model())
        assert isinstance(b, bytes)

    def test_contains_s_section(self):
        text = write_iges(self._simple_model())
        lines = text.splitlines()
        s_lines = [l for l in lines if len(l) >= 73 and l[72] == "S"]
        assert len(s_lines) >= 1

    def test_contains_g_section(self):
        text = write_iges(self._simple_model())
        lines = text.splitlines()
        g_lines = [l for l in lines if len(l) >= 73 and l[72] == "G"]
        assert len(g_lines) >= 1

    def test_contains_d_section(self):
        text = write_iges(self._simple_model())
        lines = text.splitlines()
        d_lines = [l for l in lines if len(l) >= 73 and l[72] == "D"]
        assert len(d_lines) >= 1

    def test_contains_p_section(self):
        text = write_iges(self._simple_model())
        lines = text.splitlines()
        p_lines = [l for l in lines if len(l) >= 73 and l[72] == "P"]
        assert len(p_lines) >= 1

    def test_contains_t_section(self):
        text = write_iges(self._simple_model())
        lines = text.splitlines()
        t_lines = [l for l in lines if len(l) >= 73 and l[72] == "T"]
        assert len(t_lines) == 1

    def test_line_width_80_chars(self):
        text = write_iges(self._simple_model())
        lines = [l for l in text.splitlines() if l.strip()]
        for ln in lines:
            assert len(ln) >= 72, f"Line too short: {ln!r}"
            assert len(ln) <= 80, f"Line too long: {ln!r}"


# ---------------------------------------------------------------------------
# 6. IGES writer: Line entity (Type 110)
# ---------------------------------------------------------------------------

class TestIGESWriterLine:
    def test_line_entity_type_in_d(self):
        m = IGESModel()
        m.lines.append(IGESLine(
            start=IGESPoint(1.0, 2.0, 3.0),
            end=IGESPoint(4.0, 5.0, 6.0),
        ))
        text = write_iges(m)
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        # First D-line should have entity type 110 in cols 0-7
        assert d_lines[0].strip().startswith("110")

    def test_line_params_in_p(self):
        m = IGESModel()
        m.lines.append(IGESLine(
            start=IGESPoint(0.0, 0.0, 0.0),
            end=IGESPoint(10.0, 20.0, 30.0),
        ))
        text = write_iges(m)
        p_section = "\n".join(l for l in text.splitlines() if len(l) >= 73 and l[72] == "P")
        assert "110" in p_section
        assert "10.0" in p_section or "10" in p_section

    def test_two_lines_two_d_pairs(self):
        m = IGESModel()
        m.lines.append(IGESLine(IGESPoint(0, 0, 0), IGESPoint(1, 0, 0)))
        m.lines.append(IGESLine(IGESPoint(0, 0, 0), IGESPoint(0, 1, 0)))
        text = write_iges(m)
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        # 2 entities x 2 lines each = 4 D-lines
        assert len(d_lines) == 4


# ---------------------------------------------------------------------------
# 7. IGES writer: NURBS Curve entity (Type 126)
# ---------------------------------------------------------------------------

class TestIGESWriterNURBSCurve:
    def _cubic_curve(self) -> IGESNURBSCurve:
        pts = [
            IGESPoint(0.0, 0.0, 0.0),
            IGESPoint(1.0, 2.0, 0.0),
            IGESPoint(3.0, 3.0, 0.0),
            IGESPoint(4.0, 0.0, 0.0),
        ]
        return IGESNURBSCurve(degree=3, knots=[], control_points=pts)

    def test_nurbs_curve_type_126_in_d(self):
        m = IGESModel()
        m.nurbs_curves.append(self._cubic_curve())
        text = write_iges(m)
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        assert d_lines[0].strip().startswith("126")

    def test_nurbs_curve_p_contains_degree(self):
        m = IGESModel()
        m.nurbs_curves.append(self._cubic_curve())
        text = write_iges(m)
        p_lines = "\n".join(l for l in text.splitlines() if len(l) >= 73 and l[72] == "P")
        # P-section starts with: 126,K,M where K=n-1=3, M=degree=3
        assert "126,3,3" in p_lines

    def test_auto_clamped_knots(self):
        # degree=3, 4 control points -> 8 knots
        pts = [IGESPoint(i, 0, 0) for i in range(4)]
        curve = IGESNURBSCurve(degree=3, knots=[], control_points=pts)
        m = IGESModel()
        m.nurbs_curves.append(curve)
        # Should not raise
        text = write_iges(m)
        assert text


# ---------------------------------------------------------------------------
# 8. IGES writer: NURBS Surface entity (Type 128)
# ---------------------------------------------------------------------------

class TestIGESWriterNURBSSurface:
    def _bilinear_surface(self) -> IGESNURBSSurface:
        """2x2 bilinear patch (degree 1 in U and V)."""
        net = [
            [IGESPoint(0, 0, 0), IGESPoint(0, 1, 0)],
            [IGESPoint(1, 0, 0), IGESPoint(1, 1, 0.5)],
        ]
        return IGESNURBSSurface(
            degree_u=1, degree_v=1,
            knots_u=[], knots_v=[],
            control_net=net,
        )

    def test_surface_type_128_in_d(self):
        m = IGESModel()
        m.nurbs_surfaces.append(self._bilinear_surface())
        text = write_iges(m)
        d_lines = [l for l in text.splitlines() if len(l) >= 73 and l[72] == "D"]
        assert d_lines[0].strip().startswith("128")

    def test_surface_p_contains_128(self):
        m = IGESModel()
        m.nurbs_surfaces.append(self._bilinear_surface())
        text = write_iges(m)
        p_section = "\n".join(l for l in text.splitlines() if len(l) >= 73 and l[72] == "P")
        assert "128" in p_section


# ---------------------------------------------------------------------------
# 9. Knot vector oracle
# ---------------------------------------------------------------------------

class TestUniformClampedKnots:
    def test_linear_degree1_n2(self):
        # n=2, degree=1: [0,0,1,1]
        knots = _uniform_clamped_knots(2, 1)
        assert len(knots) == 4  # n+degree+1 = 2+1+1=4
        assert knots[0] == 0.0
        assert knots[-1] == 1.0

    def test_cubic_degree3_n4(self):
        # n=4, degree=3: [0,0,0,0,1,1,1,1]
        knots = _uniform_clamped_knots(4, 3)
        assert len(knots) == 8  # 4+3+1=8
        assert knots[:4] == [0.0, 0.0, 0.0, 0.0]
        assert knots[4:] == [1.0, 1.0, 1.0, 1.0]

    def test_quadratic_degree2_n5(self):
        # n=5, degree=2: n_knots=8, n_interior=8-2*3=2
        # -> [0,0,0, 1/3, 2/3, 1,1,1]
        knots = _uniform_clamped_knots(5, 2)
        assert len(knots) == 8  # 5+2+1=8
        assert knots[0] == 0.0
        assert knots[-1] == 1.0
        # 2 interior knots at 1/3 and 2/3
        assert math.isclose(knots[3], 1 / 3, rel_tol=1e-9)
        assert math.isclose(knots[4], 2 / 3, rel_tol=1e-9)

    def test_knot_vector_length_formula(self):
        # Only test valid configurations (degree < n)
        for n, d in [(3, 2), (5, 3), (10, 1), (5, 4)]:
            knots = _uniform_clamped_knots(n, d)
            expected = n + d + 1
            assert len(knots) == expected, f"n={n}, d={d}: got {len(knots)}, expected {expected}"

    def test_knots_monotonic(self):
        knots = _uniform_clamped_knots(6, 3)
        for i in range(len(knots) - 1):
            assert knots[i] <= knots[i + 1], f"Not monotonic at {i}: {knots}"


# ---------------------------------------------------------------------------
# 10. Round-trip: write → read
# ---------------------------------------------------------------------------

class TestIGESRoundTrip:
    def test_line_roundtrip_entity_count(self):
        m = IGESModel(product_id="roundtrip", units="MM")
        m.lines.append(IGESLine(IGESPoint(0, 0, 0), IGESPoint(5, 5, 5)))
        text = write_iges(m)
        result = parse_iges(text)
        assert result.ok is True
        assert len(result.entities) >= 1

    def test_nurbs_curve_roundtrip_entity_type(self):
        m = IGESModel()
        pts = [IGESPoint(i, i * 0.5, 0) for i in range(4)]
        m.nurbs_curves.append(IGESNURBSCurve(degree=3, knots=[], control_points=pts))
        text = write_iges(m)
        result = parse_iges(text)
        assert result.ok is True
        types = [e.entity_type for e in result.entities]
        assert 126 in types

    def test_to_dict_json_serialisable(self):
        import json
        m = IGESModel()
        m.lines.append(IGESLine(IGESPoint(0, 0, 0), IGESPoint(1, 1, 1)))
        text = write_iges(m)
        result = parse_iges(text)
        d = result.to_dict()
        # Must not raise
        s = json.dumps(d)
        back = json.loads(s)
        assert back["ok"] is True


# ---------------------------------------------------------------------------
# 11. to_dict completeness
# ---------------------------------------------------------------------------

class TestIGESResultToDict:
    def test_all_keys_present(self):
        result = parse_iges(_make_iges_with_line())
        d = result.to_dict()
        expected_keys = {
            "ok", "units", "product_id", "source_system",
            "total_entities", "entity_counts",
            "nurbs_curves", "nurbs_surfaces", "brep_bodies",
            "curves_total", "surfaces_total", "warnings",
        }
        missing = expected_keys - set(d.keys())
        assert not missing, f"Missing keys: {missing}"

    def test_zero_brep_for_line_only(self):
        result = parse_iges(_make_iges_with_line())
        assert result.to_dict()["brep_bodies"] == 0

    def test_zero_nurbs_for_line_only(self):
        result = parse_iges(_make_iges_with_line())
        assert result.to_dict()["nurbs_curves"] == 0
        assert result.to_dict()["nurbs_surfaces"] == 0
