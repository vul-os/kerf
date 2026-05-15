"""
Tests for the GD&T framework (kerf_cad_core.gdt.*).

Pure-Python, hermetic — no OCC, no DB, no fixtures from disk.
Covers: datums, tolerances, modifiers, report, and validation rules.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.gdt.datums import Datum, DatumReferenceFrame, DatumType
from kerf_cad_core.gdt.tolerances import (
    GeometricTolerance,
    ToleranceSymbol,
    tolerance_category,
)
from kerf_cad_core.gdt.modifiers import ToleranceModifier, requires_feature_of_size
from kerf_cad_core.gdt.report import gdt_callout_report
from kerf_cad_core.gdt.tools import _validate_scheme


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ctx():
    """Return a minimal fake ProjectCtx (not used by pure tools)."""
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    return ProjectCtx(
        pool=None,
        storage=None,
        project_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        role="owner",
        http_client=None,
    )


def _ok(raw: str) -> dict:
    """Assert the response is not an error payload and return the parsed dict."""
    d = json.loads(raw)
    assert "error" not in d, f"Expected success payload, got error: {d}"
    return d


def _err(raw: str) -> dict:
    """Assert the response IS an error payload and return the parsed dict."""
    d = json.loads(raw)
    assert "error" in d, f"Expected error payload, got: {d}"
    return d


def _is_ok(raw: str) -> bool:
    """Return True if the response is not an error payload."""
    d = json.loads(raw)
    return "error" not in d


def _is_err(raw: str) -> bool:
    """Return True if the response is an error payload."""
    d = json.loads(raw)
    return "error" in d


# ---------------------------------------------------------------------------
# 1. DatumType enum
# ---------------------------------------------------------------------------

class TestDatumType:
    def test_all_values_present(self):
        expected = {"PLANE", "AXIS", "CENTRE_PLANE", "POINT", "LINE"}
        assert {e.value for e in DatumType} == expected

    def test_string_construction(self):
        assert DatumType("AXIS") == DatumType.AXIS


# ---------------------------------------------------------------------------
# 2. Datum dataclass
# ---------------------------------------------------------------------------

class TestDatum:
    def test_basic_construction(self):
        d = Datum(label="A", datum_type=DatumType.PLANE)
        assert d.label == "A"
        assert d.datum_type == DatumType.PLANE
        assert d.is_compound is False

    def test_string_datum_type_normalised(self):
        d = Datum(label="B", datum_type="axis")  # type: ignore[arg-type]
        assert d.datum_type == DatumType.AXIS

    def test_empty_label_raises(self):
        with pytest.raises(ValueError, match="label"):
            Datum(label="")

    def test_whitespace_label_stripped(self):
        d = Datum(label="  C  ")
        assert d.label == "C"

    def test_to_dict_round_trip(self):
        d = Datum(label="D", datum_type=DatumType.CENTRE_PLANE, feature_ref="slot-1")
        d2 = Datum.from_dict(d.to_dict())
        assert d2.label == "D"
        assert d2.datum_type == DatumType.CENTRE_PLANE
        assert d2.feature_ref == "slot-1"

    def test_compound_datum(self):
        d = Datum(label="A-B", is_compound=True)
        assert d.is_compound is True
        assert d.to_dict()["is_compound"] is True


# ---------------------------------------------------------------------------
# 3. DatumReferenceFrame
# ---------------------------------------------------------------------------

class TestDatumReferenceFrame:
    def test_empty_drf(self):
        drf = DatumReferenceFrame()
        assert drf.is_empty is True
        assert drf.labels == []

    def test_single_datum(self):
        drf = DatumReferenceFrame(primary="A")
        assert drf.labels == ["A"]
        assert not drf.is_empty

    def test_full_drf(self):
        drf = DatumReferenceFrame(primary="A", secondary="B", tertiary="C")
        assert drf.labels == ["A", "B", "C"]

    def test_tertiary_without_secondary_raises(self):
        with pytest.raises(ValueError, match="secondary"):
            DatumReferenceFrame(primary="A", tertiary="C")

    def test_str_representation(self):
        drf = DatumReferenceFrame(primary="A", secondary="B")
        assert str(drf) == "A|B"

    def test_empty_str_representation(self):
        assert str(DatumReferenceFrame()) == "(none)"

    def test_round_trip(self):
        drf = DatumReferenceFrame(primary="X", secondary="Y")
        drf2 = DatumReferenceFrame.from_dict(drf.to_dict())
        assert drf2.labels == ["X", "Y"]

    def test_whitespace_stripped(self):
        drf = DatumReferenceFrame(primary="  A  ", secondary=" B ")
        assert drf.primary == "A"
        assert drf.secondary == "B"


# ---------------------------------------------------------------------------
# 4. ToleranceSymbol and categories
# ---------------------------------------------------------------------------

class TestToleranceSymbol:
    def test_all_14_symbols_present(self):
        symbols = {s.value for s in ToleranceSymbol}
        required = {
            "FLATNESS", "STRAIGHTNESS", "CIRCULARITY", "CYLINDRICITY",
            "PROFILE_LINE", "PROFILE_SURFACE",
            "PARALLELISM", "PERPENDICULARITY", "ANGULARITY",
            "POSITION", "CONCENTRICITY", "SYMMETRY",
            "RUNOUT", "TOTAL_RUNOUT",
        }
        assert required.issubset(symbols)

    def test_form_category(self):
        for sym in [ToleranceSymbol.FLATNESS, ToleranceSymbol.STRAIGHTNESS,
                    ToleranceSymbol.CIRCULARITY, ToleranceSymbol.CYLINDRICITY]:
            assert tolerance_category(sym) == "form"

    def test_runout_category(self):
        assert tolerance_category(ToleranceSymbol.RUNOUT) == "runout"
        assert tolerance_category(ToleranceSymbol.TOTAL_RUNOUT) == "runout"

    def test_location_category(self):
        assert tolerance_category(ToleranceSymbol.POSITION) == "location"

    def test_orientation_category(self):
        assert tolerance_category(ToleranceSymbol.PERPENDICULARITY) == "orientation"


# ---------------------------------------------------------------------------
# 5. ToleranceModifier
# ---------------------------------------------------------------------------

class TestToleranceModifier:
    def test_mmc_requires_fos(self):
        assert requires_feature_of_size(ToleranceModifier.MMC) is True

    def test_lmc_requires_fos(self):
        assert requires_feature_of_size(ToleranceModifier.LMC) is True

    def test_rfs_requires_fos(self):
        assert requires_feature_of_size(ToleranceModifier.RFS) is True

    def test_projected_not_fos(self):
        assert requires_feature_of_size(ToleranceModifier.PROJECTED) is False

    def test_tangent_not_fos(self):
        assert requires_feature_of_size(ToleranceModifier.TANGENT) is False


# ---------------------------------------------------------------------------
# 6. GeometricTolerance
# ---------------------------------------------------------------------------

class TestGeometricTolerance:
    def test_basic(self):
        t = GeometricTolerance(
            feature_name="face-top",
            symbol=ToleranceSymbol.FLATNESS,
            tolerance_value=0.05,
        )
        assert t.category == "form"
        assert t.tolerance_value == 0.05

    def test_string_symbol_normalised(self):
        t = GeometricTolerance(
            feature_name="bore",
            symbol="position",  # type: ignore[arg-type]
            tolerance_value=0.1,
        )
        assert t.symbol == ToleranceSymbol.POSITION

    def test_zero_value_raises(self):
        with pytest.raises(ValueError):
            GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS,
                               tolerance_value=0)

    def test_negative_value_raises(self):
        with pytest.raises(ValueError):
            GeometricTolerance(feature_name="f", symbol=ToleranceSymbol.FLATNESS,
                               tolerance_value=-0.01)

    def test_string_modifiers_normalised(self):
        t = GeometricTolerance(
            feature_name="bore",
            symbol=ToleranceSymbol.POSITION,
            tolerance_value=0.05,
            modifiers=["mmc"],  # type: ignore[list-item]
            is_feature_of_size=True,
        )
        assert ToleranceModifier.MMC in t.modifiers

    def test_round_trip(self):
        t = GeometricTolerance(
            feature_name="slot-A",
            symbol=ToleranceSymbol.SYMMETRY,
            tolerance_value=0.02,
            datum_ref=DatumReferenceFrame(primary="A"),
            modifiers=[],
            note="centre plane ref",
        )
        d = t.to_dict()
        t2 = GeometricTolerance.from_dict(d)
        assert t2.feature_name == "slot-A"
        assert t2.symbol == ToleranceSymbol.SYMMETRY
        assert t2.datum_ref.primary == "A"

    def test_diameter_zone(self):
        t = GeometricTolerance(
            feature_name="pin",
            symbol=ToleranceSymbol.POSITION,
            tolerance_value=0.05,
            diameter_zone=True,
        )
        assert t.to_dict()["diameter_zone"] is True


# ---------------------------------------------------------------------------
# 7. gdt_callout_report (pure function)
# ---------------------------------------------------------------------------

class TestCalloutReport:
    def _flatness_dict(self, val=0.05, fname="face-1"):
        return {
            "feature_name": fname,
            "symbol": "FLATNESS",
            "tolerance_value": val,
        }

    def test_empty_features(self):
        r = gdt_callout_report([])
        assert r["count"] == 0
        assert r["callouts"] == []
        assert "Total: 0" in r["text"]

    def test_single_form_callout(self):
        r = gdt_callout_report([self._flatness_dict()])
        assert r["count"] == 1
        assert r["by_category"] == {"form": 1}
        assert "face-1" in r["callouts"][0]

    def test_symbol_char_in_callout(self):
        r = gdt_callout_report([self._flatness_dict()])
        assert "⏥" in r["callouts"][0]

    def test_diameter_prefix_in_callout(self):
        r = gdt_callout_report([{
            "feature_name": "bore",
            "symbol": "POSITION",
            "tolerance_value": 0.05,
            "diameter_zone": True,
            "datum_ref": {"primary": "A"},
        }])
        assert "⌀" in r["callouts"][0]

    def test_modifier_in_callout(self):
        r = gdt_callout_report([{
            "feature_name": "bore",
            "symbol": "POSITION",
            "tolerance_value": 0.05,
            "diameter_zone": True,
            "datum_ref": {"primary": "A"},
            "modifiers": ["MMC"],
            "is_feature_of_size": True,
        }])
        assert "(M)" in r["callouts"][0]

    def test_datum_labels_in_callout(self):
        r = gdt_callout_report([{
            "feature_name": "pin",
            "symbol": "POSITION",
            "tolerance_value": 0.1,
            "datum_ref": {"primary": "A", "secondary": "B", "tertiary": "C"},
        }])
        text = r["callouts"][0]
        assert "A" in text and "B" in text and "C" in text

    def test_multiple_features_by_category(self):
        features = [
            {"feature_name": "f1", "symbol": "FLATNESS", "tolerance_value": 0.01},
            {"feature_name": "f2", "symbol": "FLATNESS", "tolerance_value": 0.02},
            {"feature_name": "f3", "symbol": "POSITION", "tolerance_value": 0.05,
             "datum_ref": {"primary": "A"}},
            {"feature_name": "f4", "symbol": "PARALLELISM", "tolerance_value": 0.03,
             "datum_ref": {"primary": "A"}},
        ]
        r = gdt_callout_report(features)
        assert r["count"] == 4
        assert r["by_category"]["form"] == 2
        assert r["by_category"]["location"] == 1
        assert r["by_category"]["orientation"] == 1

    def test_parse_error_in_report(self):
        bad = [{"feature_name": "", "symbol": "FLATNESS", "tolerance_value": 0.1}]
        r = gdt_callout_report(bad)
        assert r["count"] == 0
        assert len(r["parse_errors"]) == 1


# ---------------------------------------------------------------------------
# 8. _validate_scheme (pure function)
# ---------------------------------------------------------------------------

class TestValidateScheme:
    def _axis_datum(self, label="A"):
        return {"label": label, "datum_type": "AXIS"}

    def _plane_datum(self, label="A"):
        return {"label": label, "datum_type": "PLANE"}

    def _centre_plane_datum(self, label="A"):
        return {"label": label, "datum_type": "CENTRE_PLANE"}

    def test_valid_flatness_no_datum(self):
        result = _validate_scheme(
            datums=[],
            tolerances=[{"feature_name": "f", "symbol": "FLATNESS",
                         "tolerance_value": 0.05}],
        )
        assert result["ok"] is True
        assert result["errors"] == []

    def test_position_without_datum_fails(self):
        result = _validate_scheme(
            datums=[],
            tolerances=[{"feature_name": "bore", "symbol": "POSITION",
                         "tolerance_value": 0.1}],
        )
        assert result["ok"] is False
        assert any("POSITION" in e for e in result["errors"])

    def test_position_with_datum_passes(self):
        result = _validate_scheme(
            datums=[self._plane_datum("A")],
            tolerances=[{"feature_name": "bore", "symbol": "POSITION",
                         "tolerance_value": 0.1,
                         "datum_ref": {"primary": "A"}}],
        )
        assert result["ok"] is True

    def test_concentricity_requires_axis_datum(self):
        result = _validate_scheme(
            datums=[self._plane_datum("A")],
            tolerances=[{"feature_name": "outer-dia", "symbol": "CONCENTRICITY",
                         "tolerance_value": 0.01,
                         "datum_ref": {"primary": "A"}}],
        )
        assert result["ok"] is False
        assert any("AXIS" in e or "CENTRE_PLANE" in e for e in result["errors"])

    def test_concentricity_with_axis_datum_passes(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{"feature_name": "outer-dia", "symbol": "CONCENTRICITY",
                         "tolerance_value": 0.01,
                         "datum_ref": {"primary": "A"}}],
        )
        assert result["ok"] is True

    def test_symmetry_requires_centre_plane_or_axis(self):
        result = _validate_scheme(
            datums=[self._plane_datum("A")],
            tolerances=[{"feature_name": "slot", "symbol": "SYMMETRY",
                         "tolerance_value": 0.02,
                         "datum_ref": {"primary": "A"}}],
        )
        assert result["ok"] is False

    def test_symmetry_with_centre_plane_datum_passes(self):
        result = _validate_scheme(
            datums=[self._centre_plane_datum("A")],
            tolerances=[{"feature_name": "slot", "symbol": "SYMMETRY",
                         "tolerance_value": 0.02,
                         "datum_ref": {"primary": "A"}}],
        )
        assert result["ok"] is True

    def test_mmc_without_fos_fails(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{
                "feature_name": "bore",
                "symbol": "POSITION",
                "tolerance_value": 0.05,
                "datum_ref": {"primary": "A"},
                "modifiers": ["MMC"],
                "is_feature_of_size": False,
            }],
        )
        assert result["ok"] is False
        assert any("MMC" in e for e in result["errors"])

    def test_mmc_with_fos_passes(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{
                "feature_name": "bore",
                "symbol": "POSITION",
                "tolerance_value": 0.05,
                "datum_ref": {"primary": "A"},
                "modifiers": ["MMC"],
                "is_feature_of_size": True,
            }],
        )
        assert result["ok"] is True

    def test_runout_requires_exactly_one_axis(self):
        # Two datums — should fail
        result = _validate_scheme(
            datums=[self._axis_datum("A"), self._axis_datum("B")],
            tolerances=[{
                "feature_name": "od",
                "symbol": "RUNOUT",
                "tolerance_value": 0.02,
                "datum_ref": {"primary": "A", "secondary": "B"},
            }],
        )
        assert result["ok"] is False
        assert any("exactly one" in e for e in result["errors"])

    def test_runout_requires_axis_type(self):
        result = _validate_scheme(
            datums=[self._plane_datum("A")],
            tolerances=[{
                "feature_name": "od",
                "symbol": "RUNOUT",
                "tolerance_value": 0.02,
                "datum_ref": {"primary": "A"},
            }],
        )
        assert result["ok"] is False
        assert any("AXIS" in e for e in result["errors"])

    def test_runout_with_axis_datum_passes(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{
                "feature_name": "od",
                "symbol": "RUNOUT",
                "tolerance_value": 0.02,
                "datum_ref": {"primary": "A"},
            }],
        )
        assert result["ok"] is True

    def test_total_runout_same_rules(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{
                "feature_name": "od",
                "symbol": "TOTAL_RUNOUT",
                "tolerance_value": 0.04,
                "datum_ref": {"primary": "A"},
            }],
        )
        assert result["ok"] is True

    def test_multiple_errors_all_reported(self):
        result = _validate_scheme(
            datums=[self._plane_datum("A")],
            tolerances=[
                {"feature_name": "bore", "symbol": "POSITION",
                 "tolerance_value": 0.05},  # missing datum
                {"feature_name": "od", "symbol": "RUNOUT",
                 "tolerance_value": 0.02,
                 "datum_ref": {"primary": "A"}},  # plane, not axis
            ],
        )
        assert result["ok"] is False
        assert len(result["errors"]) >= 2

    def test_projected_modifier_missing_height_fails(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{
                "feature_name": "threaded-hole",
                "symbol": "POSITION",
                "tolerance_value": 0.1,
                "datum_ref": {"primary": "A"},
                "modifiers": ["PROJECTED"],
                "is_feature_of_size": True,
            }],
        )
        assert result["ok"] is False
        assert any("projected_zone_height" in e for e in result["errors"])

    def test_projected_modifier_with_height_passes(self):
        result = _validate_scheme(
            datums=[self._axis_datum("A")],
            tolerances=[{
                "feature_name": "threaded-hole",
                "symbol": "POSITION",
                "tolerance_value": 0.1,
                "datum_ref": {"primary": "A"},
                "modifiers": ["PROJECTED"],
                "is_feature_of_size": True,
                "projected_zone_height": 10.0,
            }],
        )
        assert result["ok"] is True

    def test_empty_tolerances_ok(self):
        result = _validate_scheme(datums=[], tolerances=[])
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# 9. LLM tool: gdt_apply_datum
# ---------------------------------------------------------------------------

class TestToolApplyDatum:
    def setup_method(self):
        from kerf_cad_core.gdt.tools import run_gdt_apply_datum
        self._tool = run_gdt_apply_datum
        self._ctx = _make_ctx()

    def _call(self, **kwargs):
        return _run(self._tool(self._ctx, json.dumps(kwargs).encode()))

    def test_basic_plane_datum(self):
        d = _ok(self._call(label="A"))
        assert d["datum"]["label"] == "A"
        assert d["datum"]["datum_type"] == "PLANE"

    def test_axis_datum(self):
        d = _ok(self._call(label="B", datum_type="AXIS"))
        assert d["datum"]["datum_type"] == "AXIS"

    def test_missing_label_error(self):
        assert _is_err(self._call())

    def test_invalid_datum_type_error(self):
        assert _is_err(self._call(label="A", datum_type="INVALID_TYPE"))

    def test_feature_ref_stored(self):
        d = _ok(self._call(label="C", feature_ref="face-3"))
        assert d["datum"]["feature_ref"] == "face-3"


# ---------------------------------------------------------------------------
# 10. LLM tool: gdt_apply_tolerance
# ---------------------------------------------------------------------------

class TestToolApplyTolerance:
    def setup_method(self):
        from kerf_cad_core.gdt.tools import run_gdt_apply_tolerance
        self._tool = run_gdt_apply_tolerance
        self._ctx = _make_ctx()

    def _call(self, **kwargs):
        return _run(self._tool(self._ctx, json.dumps(kwargs).encode()))

    def test_basic_flatness(self):
        d = _ok(self._call(
            feature_name="top-face",
            symbol="FLATNESS",
            tolerance_value=0.05,
        ))
        assert d["tolerance"]["symbol"] == "FLATNESS"
        assert d["tolerance"]["tolerance_value"] == 0.05

    def test_position_with_datum(self):
        d = _ok(self._call(
            feature_name="bore",
            symbol="POSITION",
            tolerance_value=0.1,
            diameter_zone=True,
            datum_ref={"primary": "A", "secondary": "B"},
        ))
        t = d["tolerance"]
        assert t["diameter_zone"] is True
        assert t["datum_ref"]["primary"] == "A"

    def test_missing_feature_name_error(self):
        assert _is_err(self._call(symbol="FLATNESS", tolerance_value=0.05))

    def test_invalid_symbol_error(self):
        assert _is_err(self._call(feature_name="f", symbol="CURVINESS", tolerance_value=0.05))

    def test_zero_tolerance_error(self):
        assert _is_err(self._call(feature_name="f", symbol="FLATNESS", tolerance_value=0))

    def test_modifier_stored(self):
        d = _ok(self._call(
            feature_name="pin",
            symbol="POSITION",
            tolerance_value=0.05,
            datum_ref={"primary": "A"},
            modifiers=["MMC"],
            is_feature_of_size=True,
        ))
        assert "MMC" in d["tolerance"]["modifiers"]


# ---------------------------------------------------------------------------
# 11. LLM tool: gdt_validate_scheme
# ---------------------------------------------------------------------------

class TestToolValidateScheme:
    def setup_method(self):
        from kerf_cad_core.gdt.tools import run_gdt_validate_scheme
        self._tool = run_gdt_validate_scheme
        self._ctx = _make_ctx()

    def _call(self, **kwargs):
        return _run(self._tool(self._ctx, json.dumps(kwargs).encode()))

    def test_valid_scheme(self):
        d = _ok(self._call(
            datums=[{"label": "A", "datum_type": "PLANE"}],
            tolerances=[{
                "feature_name": "f",
                "symbol": "FLATNESS",
                "tolerance_value": 0.05,
            }],
        ))
        assert d["ok"] is True

    def test_invalid_scheme_position_no_datum(self):
        d = _ok(self._call(
            datums=[],
            tolerances=[{
                "feature_name": "bore",
                "symbol": "POSITION",
                "tolerance_value": 0.1,
            }],
        ))
        assert d["ok"] is False

    def test_missing_tolerances_arg_error(self):
        assert _is_err(self._call(datums=[]))


# ---------------------------------------------------------------------------
# 12. LLM tool: gdt_callout_report
# ---------------------------------------------------------------------------

class TestToolCalloutReport:
    def setup_method(self):
        from kerf_cad_core.gdt.tools import run_gdt_callout_report
        self._tool = run_gdt_callout_report
        self._ctx = _make_ctx()

    def _call(self, **kwargs):
        return _run(self._tool(self._ctx, json.dumps(kwargs).encode()))

    def test_basic_report(self):
        d = _ok(self._call(
            features=[{
                "feature_name": "top",
                "symbol": "FLATNESS",
                "tolerance_value": 0.05,
            }]
        ))
        assert d["count"] == 1
        assert len(d["callouts"]) == 1

    def test_missing_features_error(self):
        assert _is_err(self._call())

    def test_features_not_list_error(self):
        assert _is_err(self._call(features={"bad": "dict"}))
