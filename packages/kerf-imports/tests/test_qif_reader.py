"""
test_qif_reader.py — pytest suite for qif_reader.py.

All fixtures are synthetic QIF 3.0 XML strings constructed in-test.
No real QIF files are used.  Tests cover:
  - characteristic count parsing
  - nominal / actual / tolerance reading
  - deviation = actual - nominal
  - in/out-of-tolerance status (at least one FAIL)
  - datum capture
  - summary pass/fail counts
  - namespace-prefixed XML
  - malformed XML -> {"ok": False}
  - unknown sections skipped with warning
  - features (point / circle)
  - part name extraction
  - missing nominal / missing actual graceful handling
  - tolerance block vs single-value tolerance
  - bytes input (UTF-8)
  - empty QIF document
  - characteristic with no status -> status is None
  - bilateral tolerance stored correctly (upper > 0, lower < 0)
  - summary totals are additive
  - characteristic type extracted from designator
"""

from __future__ import annotations

import pytest

from kerf_imports.qif_reader import parse_qif


# ---------------------------------------------------------------------------
# Synthetic fixture helpers
# ---------------------------------------------------------------------------

def _bare_doc(body: str, part_name: str = "TestPart") -> str:
    """Wrap body in a minimal bare QIFDocument (no namespace prefixes)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<QIFDocument>\n'
        '  <Product>\n'
        '    <PartSet>\n'
        '      <Part id="p1">\n'
        f'        <Name>{part_name}</Name>\n'
        '      </Part>\n'
        '    </PartSet>\n'
        '  </Product>\n'
        + body +
        '\n</QIFDocument>\n'
    )


def _ns_doc(body: str, part_name: str = "NSPart") -> str:
    """Wrap body in a QIFDocument with namespace prefixes."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<qif:QIFDocument xmlns:qif="http://qifstandards.org/xsd/qif3">\n'
        '  <qif:Product>\n'
        '    <qif:PartSet>\n'
        '      <qif:Part id="p1">\n'
        f'        <qif:Name>{part_name}</qif:Name>\n'
        '      </qif:Part>\n'
        '    </qif:PartSet>\n'
        '  </qif:Product>\n'
        + body +
        '\n</qif:QIFDocument>\n'
    )


# ---------------------------------------------------------------------------
# Minimal QIF with 3 characteristics: 2 PASS + 1 FAIL, 1 datum, 1 circle feature
# ---------------------------------------------------------------------------

_MINIMAL_THREE_CHAR = _bare_doc(
    '<MeasurementResources>\n'
    '  <MeasuredCharacteristics>\n'
    '    <CharacteristicItems>\n'
    '      <CharacteristicItem id="c1">\n'
    '        <Name>Diameter 1</Name>\n'
    '        <CharacteristicDesignator><Designator>dimension</Designator></CharacteristicDesignator>\n'
    '        <NominalValue>10.0</NominalValue>\n'
    '        <Tolerance>\n'
    '          <UpperTolerance>0.05</UpperTolerance>\n'
    '          <LowerTolerance>-0.05</LowerTolerance>\n'
    '        </Tolerance>\n'
    '      </CharacteristicItem>\n'
    '      <CharacteristicItem id="c2">\n'
    '        <Name>Flatness 1</Name>\n'
    '        <CharacteristicDesignator><Designator>flatness</Designator></CharacteristicDesignator>\n'
    '        <NominalValue>0.0</NominalValue>\n'
    '        <ToleranceValue>0.02</ToleranceValue>\n'
    '      </CharacteristicItem>\n'
    '      <CharacteristicItem id="c3">\n'
    '        <Name>Diameter 2</Name>\n'
    '        <CharacteristicDesignator><Designator>dimension</Designator></CharacteristicDesignator>\n'
    '        <NominalValue>25.0</NominalValue>\n'
    '        <Tolerance>\n'
    '          <UpperTolerance>0.1</UpperTolerance>\n'
    '          <LowerTolerance>-0.1</LowerTolerance>\n'
    '        </Tolerance>\n'
    '      </CharacteristicItem>\n'
    '    </CharacteristicItems>\n'
    '  </MeasuredCharacteristics>\n'
    '</MeasurementResources>\n'
    '<DatumDefinitions>\n'
    '  <DatumDefinition id="d1">\n'
    '    <DatumLabel>A</DatumLabel>\n'
    '    <FeatureId>f1</FeatureId>\n'
    '  </DatumDefinition>\n'
    '</DatumDefinitions>\n'
    '<Features>\n'
    '  <FeatureItems>\n'
    '    <CircleFeature id="f1">\n'
    '      <Name>Circle 1</Name>\n'
    '      <Nominal>\n'
    '        <Location><X>0.0</X><Y>0.0</Y><Z>0.0</Z></Location>\n'
    '        <Radius>5.0</Radius>\n'
    '      </Nominal>\n'
    '      <Actual>\n'
    '        <Location><X>0.01</X><Y>0.0</Y><Z>0.0</Z></Location>\n'
    '        <Radius>5.015</Radius>\n'
    '      </Actual>\n'
    '    </CircleFeature>\n'
    '  </FeatureItems>\n'
    '</Features>\n'
    '<MeasurementResults>\n'
    '  <MeasurementResult id="mr1">\n'
    '    <MeasuredCharacteristics>\n'
    '      <MeasuredCharacteristic>\n'
    '        <CharacteristicItemId>c1</CharacteristicItemId>\n'
    '        <Value>10.03</Value>\n'
    '        <Status><PassFail>PASS</PassFail></Status>\n'
    '      </MeasuredCharacteristic>\n'
    '      <MeasuredCharacteristic>\n'
    '        <CharacteristicItemId>c2</CharacteristicItemId>\n'
    '        <Value>0.005</Value>\n'
    '        <Status><PassFail>PASS</PassFail></Status>\n'
    '      </MeasuredCharacteristic>\n'
    '      <MeasuredCharacteristic>\n'
    '        <CharacteristicItemId>c3</CharacteristicItemId>\n'
    '        <Value>25.15</Value>\n'
    '        <Status><PassFail>FAIL</PassFail></Status>\n'
    '      </MeasuredCharacteristic>\n'
    '    </MeasuredCharacteristics>\n'
    '  </MeasurementResult>\n'
    '</MeasurementResults>\n'
)


def _get_char(result: dict, cid: str) -> dict:
    for c in result["characteristics"]:
        if c["id"] == cid:
            return c
    raise KeyError(f"characteristic {cid!r} not found in result")


# ---------------------------------------------------------------------------
# Tests: basic parsing
# ---------------------------------------------------------------------------

class TestCharacteristicCount:
    def test_three_characteristics_parsed(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["ok"] is True
        assert len(result["characteristics"]) == 3

    def test_characteristic_ids_present(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        ids = {c["id"] for c in result["characteristics"]}
        assert {"c1", "c2", "c3"} == ids


class TestNominalAndTolerance:
    def test_nominal_value_c1(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c1 = _get_char(result, "c1")
        assert c1["nominal"] == pytest.approx(10.0)

    def test_nominal_value_c3(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c3 = _get_char(result, "c3")
        assert c3["nominal"] == pytest.approx(25.0)

    def test_bilateral_tolerance_upper(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c1 = _get_char(result, "c1")
        assert c1["upper_tol"] == pytest.approx(0.05)

    def test_bilateral_tolerance_lower(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c1 = _get_char(result, "c1")
        assert c1["lower_tol"] == pytest.approx(-0.05)

    def test_single_tolerance_value_symmetric(self):
        # c2 uses <ToleranceValue>0.02</ToleranceValue> — should expand symmetrically
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c2 = _get_char(result, "c2")
        assert c2["upper_tol"] == pytest.approx(0.02)
        assert c2["lower_tol"] == pytest.approx(-0.02)


class TestActualAndDeviation:
    def test_actual_value_c1(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c1 = _get_char(result, "c1")
        assert c1["actual"] == pytest.approx(10.03)

    def test_deviation_equals_actual_minus_nominal_c1(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c1 = _get_char(result, "c1")
        assert c1["deviation"] == pytest.approx(10.03 - 10.0)

    def test_deviation_c3_out_of_tolerance(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c3 = _get_char(result, "c3")
        assert c3["deviation"] == pytest.approx(25.15 - 25.0)

    def test_actual_c2(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c2 = _get_char(result, "c2")
        assert c2["actual"] == pytest.approx(0.005)


class TestPassFail:
    def test_c1_is_pass(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert _get_char(result, "c1")["status"] == "PASS"

    def test_c2_is_pass(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert _get_char(result, "c2")["status"] == "PASS"

    def test_c3_is_fail(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert _get_char(result, "c3")["status"] == "FAIL"

    def test_at_least_one_fail_present(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        statuses = [c["status"] for c in result["characteristics"]]
        assert "FAIL" in statuses


class TestSummary:
    def test_summary_total(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["summary"]["total"] == 3

    def test_summary_passed(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["summary"]["passed"] == 2

    def test_summary_failed(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["summary"]["failed"] == 1

    def test_summary_totals_are_consistent(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        s = result["summary"]
        # passed + failed may be <= total (some may have no status)
        assert s["passed"] + s["failed"] <= s["total"]


# ---------------------------------------------------------------------------
# Tests: datum capture
# ---------------------------------------------------------------------------

class TestDatums:
    def test_datum_count(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert len(result["datums"]) == 1

    def test_datum_label(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        datum = result["datums"][0]
        assert datum["label"] == "A"

    def test_datum_feature_id(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        datum = result["datums"][0]
        assert datum["feature_id"] == "f1"


# ---------------------------------------------------------------------------
# Tests: features
# ---------------------------------------------------------------------------

class TestFeatures:
    def test_feature_count(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert len(result["features"]) == 1

    def test_feature_type(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["features"][0]["type"] == "CircleFeature"

    def test_feature_name(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["features"][0]["name"] == "Circle 1"

    def test_feature_nominal_radius(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        f = result["features"][0]
        assert f["nominal"]["radius"] == pytest.approx(5.0)

    def test_feature_actual_radius(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        f = result["features"][0]
        assert f["actual"]["radius"] == pytest.approx(5.015)


# ---------------------------------------------------------------------------
# Tests: namespace-prefixed XML
# ---------------------------------------------------------------------------

_NS_BODY = (
    '<qif:MeasurementResources>\n'
    '  <qif:MeasuredCharacteristics>\n'
    '    <qif:CharacteristicItems>\n'
    '      <qif:CharacteristicItem id="n1">\n'
    '        <qif:Name>Width</qif:Name>\n'
    '        <qif:NominalValue>50.0</qif:NominalValue>\n'
    '        <qif:ToleranceValue>0.1</qif:ToleranceValue>\n'
    '      </qif:CharacteristicItem>\n'
    '    </qif:CharacteristicItems>\n'
    '  </qif:MeasuredCharacteristics>\n'
    '</qif:MeasurementResources>\n'
    '<qif:MeasurementResults>\n'
    '  <qif:MeasurementResult id="mr1">\n'
    '    <qif:MeasuredCharacteristics>\n'
    '      <qif:MeasuredCharacteristic>\n'
    '        <qif:CharacteristicItemId>n1</qif:CharacteristicItemId>\n'
    '        <qif:Value>50.05</qif:Value>\n'
    '        <qif:Status><qif:PassFail>PASS</qif:PassFail></qif:Status>\n'
    '      </qif:MeasuredCharacteristic>\n'
    '    </qif:MeasuredCharacteristics>\n'
    '  </qif:MeasurementResult>\n'
    '</qif:MeasurementResults>\n'
)


class TestNamespacePrefixed:
    def test_ns_prefixed_parses_ok(self):
        result = parse_qif(_ns_doc(_NS_BODY, part_name="NSTestPart"))
        assert result["ok"] is True

    def test_ns_prefixed_char_count(self):
        result = parse_qif(_ns_doc(_NS_BODY, part_name="NSTestPart"))
        assert len(result["characteristics"]) == 1

    def test_ns_prefixed_nominal(self):
        result = parse_qif(_ns_doc(_NS_BODY, part_name="NSTestPart"))
        c = result["characteristics"][0]
        assert c["nominal"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Tests: malformed XML
# ---------------------------------------------------------------------------

class TestMalformedXML:
    def test_malformed_returns_not_ok(self):
        result = parse_qif("<QIFDocument><Unclosed>")
        assert result["ok"] is False

    def test_malformed_has_reason(self):
        result = parse_qif("not xml at all <<<")
        assert result["ok"] is False
        assert "reason" in result

    def test_empty_string_returns_error(self):
        result = parse_qif("")
        assert result["ok"] is False

    def test_bytes_malformed(self):
        result = parse_qif(b"\xff\xfe bad xml <<<")
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Tests: unknown sections skipped
# ---------------------------------------------------------------------------

class TestUnknownSectionsSkipped:
    def test_unknown_section_does_not_raise(self):
        body = (
            '<FutureQIFExtension><SomethingUnknown>blah</SomethingUnknown></FutureQIFExtension>\n'
            '<MeasurementResources>\n'
            '  <MeasuredCharacteristics>\n'
            '    <CharacteristicItems>\n'
            '      <CharacteristicItem id="u1">\n'
            '        <Name>UnknownTest</Name>\n'
            '        <NominalValue>5.0</NominalValue>\n'
            '        <ToleranceValue>0.01</ToleranceValue>\n'
            '      </CharacteristicItem>\n'
            '    </CharacteristicItems>\n'
            '  </MeasuredCharacteristics>\n'
            '</MeasurementResources>\n'
        )
        result = parse_qif(_bare_doc(body))
        assert result["ok"] is True

    def test_statistics_section_emits_warning(self):
        body = '<Statistics><SomeStatisticsData>...</SomeStatisticsData></Statistics>\n'
        result = parse_qif(_bare_doc(body))
        assert result["ok"] is True
        assert any(
            "Statistics" in w or "statistic" in w.lower()
            for w in result["warnings"]
        )


# ---------------------------------------------------------------------------
# Tests: part name
# ---------------------------------------------------------------------------

class TestPartName:
    def test_part_name_extracted(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        assert result["part_name"] == "TestPart"

    def test_empty_doc_part_name_is_string(self):
        result = parse_qif('<?xml version="1.0"?><QIFDocument></QIFDocument>')
        assert result["ok"] is True
        assert isinstance(result["part_name"], str)


# ---------------------------------------------------------------------------
# Tests: bytes input
# ---------------------------------------------------------------------------

class TestBytesInput:
    def test_utf8_bytes_parsed(self):
        result = parse_qif(_MINIMAL_THREE_CHAR.encode("utf-8"))
        assert result["ok"] is True
        assert len(result["characteristics"]) == 3

    def test_utf8_bytes_nominal_correct(self):
        result = parse_qif(_MINIMAL_THREE_CHAR.encode("utf-8"))
        c1 = _get_char(result, "c1")
        assert c1["nominal"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_no_actual_value_deviation_is_none(self):
        body = (
            '<MeasurementResources>\n'
            '  <MeasuredCharacteristics>\n'
            '    <CharacteristicItems>\n'
            '      <CharacteristicItem id="e1">\n'
            '        <Name>NoActual</Name>\n'
            '        <NominalValue>5.0</NominalValue>\n'
            '        <ToleranceValue>0.1</ToleranceValue>\n'
            '      </CharacteristicItem>\n'
            '    </CharacteristicItems>\n'
            '  </MeasuredCharacteristics>\n'
            '</MeasurementResources>\n'
        )
        result = parse_qif(_bare_doc(body))
        c = _get_char(result, "e1")
        assert c["actual"] is None
        assert c["deviation"] is None

    def test_no_status_is_none(self):
        body = (
            '<MeasurementResources>\n'
            '  <MeasuredCharacteristics>\n'
            '    <CharacteristicItems>\n'
            '      <CharacteristicItem id="ns1">\n'
            '        <Name>NoStatus</Name>\n'
            '        <NominalValue>3.0</NominalValue>\n'
            '        <ToleranceValue>0.05</ToleranceValue>\n'
            '      </CharacteristicItem>\n'
            '    </CharacteristicItems>\n'
            '  </MeasuredCharacteristics>\n'
            '</MeasurementResources>\n'
            '<MeasurementResults>\n'
            '  <MeasurementResult id="mr1">\n'
            '    <MeasuredCharacteristics>\n'
            '      <MeasuredCharacteristic>\n'
            '        <CharacteristicItemId>ns1</CharacteristicItemId>\n'
            '        <Value>3.01</Value>\n'
            '      </MeasuredCharacteristic>\n'
            '    </MeasuredCharacteristics>\n'
            '  </MeasurementResult>\n'
            '</MeasurementResults>\n'
        )
        result = parse_qif(_bare_doc(body))
        c = _get_char(result, "ns1")
        assert c["status"] is None

    def test_characteristic_type_extracted(self):
        result = parse_qif(_MINIMAL_THREE_CHAR)
        c1 = _get_char(result, "c1")
        assert c1["type"] == "dimension"

    def test_summary_no_chars_all_zero(self):
        result = parse_qif('<?xml version="1.0"?><QIFDocument></QIFDocument>')
        assert result["ok"] is True
        assert result["summary"]["total"] == 0
        assert result["summary"]["passed"] == 0
        assert result["summary"]["failed"] == 0
