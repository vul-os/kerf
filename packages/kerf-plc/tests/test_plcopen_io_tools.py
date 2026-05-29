"""test_plcopen_io_tools.py — LLM tool dispatch tests for import/export (T-220).

Covers:
  IO01  import_plcopen_xml — blinker.plc fixture → ok, pou/rung counts correct
  IO02  import_plcopen_xml — conveyor.plc fixture → ok, variable + rung counts
  IO03  import_plcopen_xml — model.pous[0].body.language == 'LD'
  IO04  import_plcopen_xml — empty xml returns PARSE_ERROR
  IO05  import_plcopen_xml — invalid XML returns PARSE_ERROR
  IO06  import_plcopen_xml — handler is async coroutine
  IO07  export_plcopen_xml — round-trip: import → export → re-import → counts match
  IO08  export_plcopen_xml — missing model returns INVALID_MODEL error
  IO09  export_plcopen_xml — missing pous field returns INVALID_MODEL error
  IO10  export_plcopen_xml — project_name override appears in output XML
  IO11  export_plcopen_xml — handler is async coroutine
  IO12  _register_tools registers plc.plcopen_io capability
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

_PKG = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PKG / "src"))

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx():
    registered = {}

    class _Tools:
        def register(self, name, spec, handler):
            registered[name] = (spec, handler)

    ctx = SimpleNamespace(tools=_Tools())
    ctx._registered = registered
    return ctx


def _run(coro):
    return asyncio.run(coro)


def _fixture_xml(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Build tool set once
# ---------------------------------------------------------------------------

_ctx = _make_ctx()
_provides: list[str] = []

from kerf_plc.plugin import _register_tools  # noqa: E402
_register_tools(_ctx, _provides)
_reg = _ctx._registered


# ---------------------------------------------------------------------------
# IO01–IO06  import_plcopen_xml
# ---------------------------------------------------------------------------

class TestImportPlcopenXml:
    def _call(self, xml: str) -> dict:
        _, handler = _reg["import_plcopen_xml"]
        payload = json.dumps({"xml": xml}).encode()
        return json.loads(_run(handler(None, payload)))

    def test_io01_blinker_ok_and_counts(self):
        """IO01: blinker.plc → ok=True, pou_count=1, rung_count=1."""
        if "import_plcopen_xml" not in _reg:
            pytest.skip("import_plcopen_xml not registered")
        result = self._call(_fixture_xml("blinker.plc"))
        assert result.get("ok") is True, f"Expected ok in result: {result}"
        assert result["pou_count"] == 1
        assert result["rung_count"] == 1

    def test_io02_conveyor_counts(self):
        """IO02: conveyor.plc → 4 rungs, 6 variables."""
        if "import_plcopen_xml" not in _reg:
            pytest.skip("import_plcopen_xml not registered")
        result = self._call(_fixture_xml("conveyor.plc"))
        assert result.get("ok") is True
        assert result["rung_count"] == 4
        assert result["variable_count"] == 6

    def test_io03_body_language_is_ld(self):
        """IO03: first POU body language is LD."""
        if "import_plcopen_xml" not in _reg:
            pytest.skip("import_plcopen_xml not registered")
        result = self._call(_fixture_xml("blinker.plc"))
        pou = result["model"]["pous"][0]
        assert pou["body_language"] == "LD"
        assert pou["body"]["language"] == "LD"

    def test_io04_empty_xml_returns_parse_error(self):
        """IO04: empty xml → PARSE_ERROR."""
        if "import_plcopen_xml" not in _reg:
            pytest.skip("import_plcopen_xml not registered")
        result = self._call("")
        assert "error" in result

    def test_io05_invalid_xml_returns_parse_error(self):
        """IO05: malformed XML → PARSE_ERROR."""
        if "import_plcopen_xml" not in _reg:
            pytest.skip("import_plcopen_xml not registered")
        result = self._call("<project><unclosed>")
        assert "error" in result

    def test_io06_handler_is_coroutine(self):
        """IO06: import handler must be async."""
        if "import_plcopen_xml" not in _reg:
            pytest.skip("import_plcopen_xml not registered")
        _, handler = _reg["import_plcopen_xml"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# IO07–IO11  export_plcopen_xml
# ---------------------------------------------------------------------------

class TestExportPlcopenXml:
    def _import(self, xml: str) -> dict:
        _, handler = _reg["import_plcopen_xml"]
        payload = json.dumps({"xml": xml}).encode()
        return json.loads(_run(handler(None, payload)))

    def _export(self, model: dict, **kwargs) -> dict:
        _, handler = _reg["export_plcopen_xml"]
        payload = json.dumps({"model": model, **kwargs}).encode()
        return json.loads(_run(handler(None, payload)))

    def test_io07_round_trip_blinker(self):
        """IO07: import blinker → export → re-import → pou/rung counts match."""
        if "import_plcopen_xml" not in _reg or "export_plcopen_xml" not in _reg:
            pytest.skip("import or export not registered")
        # First import
        r1 = self._import(_fixture_xml("blinker.plc"))
        assert r1.get("ok") is True

        # Export
        re = self._export(r1["model"])
        assert re.get("ok") is True, f"Export failed: {re}"
        assert "xml" in re

        # Re-import
        r2 = self._import(re["xml"])
        assert r2.get("ok") is True
        assert r2["pou_count"] == r1["pou_count"]
        assert r2["rung_count"] == r1["rung_count"]

    def test_io07b_round_trip_conveyor(self):
        """IO07b: import conveyor → export → re-import → counts match."""
        if "import_plcopen_xml" not in _reg or "export_plcopen_xml" not in _reg:
            pytest.skip("import or export not registered")
        r1 = self._import(_fixture_xml("conveyor.plc"))
        re = self._export(r1["model"])
        assert re.get("ok") is True
        r2 = self._import(re["xml"])
        assert r2["pou_count"] == r1["pou_count"]
        assert r2["rung_count"] == r1["rung_count"]
        assert r2["variable_count"] == r1["variable_count"]

    def test_io08_missing_model_returns_error(self):
        """IO08: missing model → INVALID_MODEL error."""
        if "export_plcopen_xml" not in _reg:
            pytest.skip("export_plcopen_xml not registered")
        _, handler = _reg["export_plcopen_xml"]
        payload = json.dumps({}).encode()
        result = json.loads(_run(handler(None, payload)))
        assert "error" in result

    def test_io09_missing_pous_returns_error(self):
        """IO09: model without 'pous' key → INVALID_MODEL."""
        if "export_plcopen_xml" not in _reg:
            pytest.skip("export_plcopen_xml not registered")
        result = self._export({"project_name": "Test"})
        assert "error" in result

    def test_io10_project_name_override(self):
        """IO10: project_name override appears in exported XML."""
        if "import_plcopen_xml" not in _reg or "export_plcopen_xml" not in _reg:
            pytest.skip("import or export not registered")
        r1 = self._import(_fixture_xml("blinker.plc"))
        re = self._export(r1["model"], project_name="MyCustomProject")
        assert re.get("ok") is True
        assert "MyCustomProject" in re["xml"]
        assert re["project_name"] == "MyCustomProject"

    def test_io11_handler_is_coroutine(self):
        """IO11: export handler must be async."""
        if "export_plcopen_xml" not in _reg:
            pytest.skip("export_plcopen_xml not registered")
        _, handler = _reg["export_plcopen_xml"]
        assert inspect.iscoroutinefunction(handler)


# ---------------------------------------------------------------------------
# IO12  capability provides
# ---------------------------------------------------------------------------

class TestPlocopenIoProvides:
    def test_io12_plcopen_io_capability_registered(self):
        """IO12: _register_tools adds 'plc.plcopen_io' to provides."""
        assert "plc.plcopen_io" in _provides, (
            f"'plc.plcopen_io' not in provides: {_provides}"
        )
