"""
Tests for kerf_cad_core.fem_capabilities (T-100h).

Verifies:
  - list_capabilities() returns a dict with expected structure
  - all AnalysisType members appear in the output
  - each entry has id, requires, description fields
  - requires is a list of strings (JSON-serialisable)
  - description is a non-empty string
  - the LLM tool stub spec is well-formed
  - the async handler runs and returns valid JSON
"""

from __future__ import annotations

import asyncio
import json
import pytest

from kerf_cad_core.analysis import AnalysisType
from kerf_cad_core.fem_capabilities import (
    list_capabilities,
    _FEM_CAPABILITIES_SPEC,
    _run_fem_list_capabilities,
)


class TestListCapabilities:
    def test_returns_dict(self):
        result = list_capabilities()
        assert isinstance(result, dict)

    def test_has_analysis_types_key(self):
        result = list_capabilities()
        assert "analysis_types" in result

    def test_has_n_types_key(self):
        result = list_capabilities()
        assert "n_types" in result
        assert isinstance(result["n_types"], int)
        assert result["n_types"] == len(result["analysis_types"])

    def test_all_analysis_types_present(self):
        result = list_capabilities()
        ids = {entry["id"] for entry in result["analysis_types"]}
        for member in AnalysisType:
            assert member.value in ids, (
                f"AnalysisType.{member.name} ({member.value!r}) missing from capabilities"
            )

    def test_entries_have_required_fields(self):
        result = list_capabilities()
        for entry in result["analysis_types"]:
            assert "id" in entry, f"entry missing 'id': {entry}"
            assert "requires" in entry, f"entry missing 'requires': {entry}"
            assert "description" in entry, f"entry missing 'description': {entry}"

    def test_requires_is_sorted_list_of_strings(self):
        result = list_capabilities()
        for entry in result["analysis_types"]:
            reqs = entry["requires"]
            assert isinstance(reqs, list), (
                f"{entry['id']}: requires must be a list, got {type(reqs)}"
            )
            for r in reqs:
                assert isinstance(r, str), (
                    f"{entry['id']}: requires item {r!r} is not a string"
                )
            # Must be sorted
            assert reqs == sorted(reqs), (
                f"{entry['id']}: requires list {reqs} must be sorted"
            )

    def test_description_nonempty_string(self):
        result = list_capabilities()
        for entry in result["analysis_types"]:
            desc = entry["description"]
            assert isinstance(desc, str)
            assert len(desc.strip()) > 0, (
                f"{entry['id']}: description must not be empty"
            )

    def test_output_is_json_serialisable(self):
        result = list_capabilities()
        serialised = json.dumps(result)
        parsed = json.loads(serialised)
        assert parsed["n_types"] == result["n_types"]

    def test_sorted_by_id(self):
        result = list_capabilities()
        ids = [entry["id"] for entry in result["analysis_types"]]
        assert ids == sorted(ids), "analysis_types must be sorted by id"


class TestSpecificEntries:
    """Spot-check a few specific entries."""

    def _entry(self, target_id: str) -> dict:
        result = list_capabilities()
        for entry in result["analysis_types"]:
            if entry["id"] == target_id:
                return entry
        pytest.fail(f"Entry {target_id!r} not found in capabilities")

    def test_linear_static_has_linear_solver(self):
        entry = self._entry("linear_static")
        assert "linear_solver" in entry["requires"]

    def test_nonlinear_has_nonlinear_solver(self):
        entry = self._entry("nonlinear")
        assert "nonlinear_solver" in entry["requires"]

    def test_explicit_has_explicit_integrator(self):
        entry = self._entry("explicit")
        assert "explicit_integrator" in entry["requires"]

    def test_acoustics_fem_has_acoustic_solver(self):
        entry = self._entry("acoustics_fem")
        assert "acoustic_solver" in entry["requires"]

    def test_em_field_has_em_solver_lowfreq(self):
        entry = self._entry("em_field")
        assert "em_solver_lowfreq" in entry["requires"]

    def test_em_highfreq_has_em_solver_fullwave(self):
        entry = self._entry("em_highfreq")
        assert "em_solver_fullwave" in entry["requires"]

    def test_fatigue_fem_has_fatigue_postprocessor(self):
        entry = self._entry("fatigue_fem")
        assert "fatigue_postprocessor" in entry["requires"]


class TestToolSpec:
    def test_spec_has_name(self):
        assert "name" in _FEM_CAPABILITIES_SPEC
        assert isinstance(_FEM_CAPABILITIES_SPEC["name"], str)
        assert _FEM_CAPABILITIES_SPEC["name"] == "fem_list_capabilities"

    def test_spec_has_description(self):
        assert "description" in _FEM_CAPABILITIES_SPEC
        assert len(_FEM_CAPABILITIES_SPEC["description"].strip()) > 0

    def test_spec_has_input_schema(self):
        assert "input_schema" in _FEM_CAPABILITIES_SPEC
        schema = _FEM_CAPABILITIES_SPEC["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_spec_is_json_serialisable(self):
        json.dumps(_FEM_CAPABILITIES_SPEC)


class TestAsyncHandler:
    """Test the async tool handler stub."""

    def test_handler_returns_valid_json(self):
        result_str = asyncio.get_event_loop().run_until_complete(
            _run_fem_list_capabilities(None, b"{}")
        )
        result = json.loads(result_str)
        assert result.get("ok") is True
        assert "analysis_types" in result
        assert isinstance(result["analysis_types"], list)

    def test_handler_n_types_matches_list(self):
        result_str = asyncio.get_event_loop().run_until_complete(
            _run_fem_list_capabilities(None, b"{}")
        )
        result = json.loads(result_str)
        assert result["n_types"] == len(result["analysis_types"])
