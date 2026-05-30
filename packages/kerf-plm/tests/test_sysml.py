"""
Tests for kerf_plm.sysml — MBSE / SysML 1.x digital-thread.

Oracles
-------
T1  Round-trip XMI  : export → import → identical structure (IDs, links, namespaces).
T2  Coverage report : 5 requirements, 3 satisfied → 60 %; correct uncovered list.
T3  Orphan detection: unverified requirement + orphan test → both flagged.
T4  Namespace check : SysML 1.6 vs 1.7 produce distinct namespace URIs; import
                      auto-detects from namespace.
"""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET

import pytest

from kerf_plm.sysml import (
    Requirement,
    DesignElement,
    TestCase,
    TraceabilityMatrix,
    export_xmi,
    import_xmi,
    _NS_SYSML,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_small_matrix() -> TraceabilityMatrix:
    """3 requirements, 2 designs, 2 tests — used for round-trip test."""
    reqs = [
        Requirement("REQ-001", "System shall weigh < 5 kg", satisfied_by=["DE-001"], verified_by=["TC-001"]),
        Requirement("REQ-002", "System shall survive 5G shock", satisfied_by=["DE-002"], verified_by=["TC-002"]),
        Requirement("REQ-003", "Power draw < 10 W", parent_id="REQ-002", satisfied_by=["DE-001", "DE-002"]),
    ]
    designs = [
        DesignElement("DE-001", "block", "StructuralFrame", {"material": "Al6061"}),
        DesignElement("DE-002", "part",  "PowerModule",    {"voltage": "28V"}),
    ]
    tests = [
        TestCase("TC-001", "WeightVerification",    verifies=["REQ-001"]),
        TestCase("TC-002", "ShockVerification",      verifies=["REQ-002"]),
    ]
    return TraceabilityMatrix(reqs, designs, tests)


# ---------------------------------------------------------------------------
# T1  Round-trip XMI export → import
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Export a matrix, re-import it, verify structural identity."""

    def test_roundtrip_requirement_ids(self, tmp_path):
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert set(restored.requirements.keys()) == set(matrix.requirements.keys())

    def test_roundtrip_design_element_ids(self, tmp_path):
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert set(restored.design_elements.keys()) == set(matrix.design_elements.keys())

    def test_roundtrip_test_case_ids(self, tmp_path):
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert set(restored.test_cases.keys()) == set(matrix.test_cases.keys())

    def test_roundtrip_satisfy_links(self, tmp_path):
        """REQ-001.satisfied_by == ['DE-001'] must survive export→import."""
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert "DE-001" in restored.requirements["REQ-001"].satisfied_by
        assert "DE-002" in restored.requirements["REQ-002"].satisfied_by

    def test_roundtrip_verify_links(self, tmp_path):
        """TC-001.verifies == ['REQ-001'] must survive export→import."""
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert "REQ-001" in restored.test_cases["TC-001"].verifies
        assert "REQ-002" in restored.test_cases["TC-002"].verifies

    def test_roundtrip_parent_id(self, tmp_path):
        """REQ-003.parent_id == 'REQ-002' must survive export→import."""
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert restored.requirements["REQ-003"].parent_id == "REQ-002"

    def test_roundtrip_requirement_text(self, tmp_path):
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert restored.requirements["REQ-001"].text == "System shall weigh < 5 kg"

    def test_roundtrip_design_element_kind(self, tmp_path):
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert restored.design_elements["DE-001"].kind == "block"
        assert restored.design_elements["DE-002"].kind == "part"

    def test_roundtrip_design_element_properties(self, tmp_path):
        matrix = _build_small_matrix()
        xmi_path = tmp_path / "model.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)

        assert restored.design_elements["DE-001"].properties.get("material") == "Al6061"


# ---------------------------------------------------------------------------
# T2  Coverage report: 5 requirements, 3 satisfied → 60 %
# ---------------------------------------------------------------------------

class TestCoverageReport:
    """5 requirements; 3 have design + test links; 2 uncovered."""

    def _build_coverage_matrix(self) -> TraceabilityMatrix:
        reqs = [
            Requirement("R1", "Req 1", satisfied_by=["D1"], verified_by=["T1"]),
            Requirement("R2", "Req 2", satisfied_by=["D1"], verified_by=["T1"]),
            Requirement("R3", "Req 3", satisfied_by=["D2"], verified_by=["T2"]),
            Requirement("R4", "Req 4"),   # no design, no test → uncovered
            Requirement("R5", "Req 5"),   # no design, no test → uncovered
        ]
        designs = [
            DesignElement("D1", "block", "Block1"),
            DesignElement("D2", "block", "Block2"),
        ]
        tests = [
            TestCase("T1", "Test1", verifies=["R1", "R2"]),
            TestCase("T2", "Test2", verifies=["R3"]),
        ]
        return TraceabilityMatrix(reqs, designs, tests)

    def test_covered_count(self):
        report = self._build_coverage_matrix().coverage_report()
        assert report["covered"] == 3

    def test_uncovered_count(self):
        report = self._build_coverage_matrix().coverage_report()
        assert report["uncovered"] == 2

    def test_total_count(self):
        report = self._build_coverage_matrix().coverage_report()
        assert report["total"] == 5

    def test_coverage_pct(self):
        report = self._build_coverage_matrix().coverage_report()
        assert report["coverage_pct"] == pytest.approx(60.0, abs=0.01)

    def test_uncovered_ids(self):
        report = self._build_coverage_matrix().coverage_report()
        # R4 and R5 have no design and no test → appear in both orphaned + unverified
        assert "R4" in report["orphaned_requirements"]
        assert "R5" in report["orphaned_requirements"]

    def test_unverified_ids(self):
        report = self._build_coverage_matrix().coverage_report()
        assert "R4" in report["unverified_requirements"]
        assert "R5" in report["unverified_requirements"]

    def test_covered_requirements_not_in_uncovered(self):
        report = self._build_coverage_matrix().coverage_report()
        assert "R1" not in report["orphaned_requirements"]
        assert "R2" not in report["orphaned_requirements"]
        assert "R3" not in report["orphaned_requirements"]


# ---------------------------------------------------------------------------
# T3  Orphan detection
# ---------------------------------------------------------------------------

class TestOrphanDetection:
    """Unverified requirement + orphan test → both flagged."""

    def _build_orphan_matrix(self) -> TraceabilityMatrix:
        reqs = [
            Requirement("R1", "Satisfied+verified req", satisfied_by=["D1"], verified_by=["T1"]),
            Requirement("R2", "Unsatisfied req — orphan"),  # no design, no test
        ]
        designs = [DesignElement("D1", "block", "Block1")]
        tests = [
            TestCase("T1", "NormalTest", verifies=["R1"]),
            TestCase("T_ORPHAN", "OrphanTest", verifies=[]),  # verifies nothing
        ]
        return TraceabilityMatrix(reqs, designs, tests)

    def test_orphan_requirement_flagged(self):
        report = self._build_orphan_matrix().coverage_report()
        assert "R2" in report["orphaned_requirements"]

    def test_orphan_test_flagged(self):
        report = self._build_orphan_matrix().coverage_report()
        assert "T_ORPHAN" in report["orphaned_tests"]

    def test_normal_requirement_not_orphaned(self):
        report = self._build_orphan_matrix().coverage_report()
        assert "R1" not in report["orphaned_requirements"]

    def test_normal_test_not_orphaned(self):
        report = self._build_orphan_matrix().coverage_report()
        assert "T1" not in report["orphaned_tests"]

    def test_unverified_requirement_listed(self):
        report = self._build_orphan_matrix().coverage_report()
        assert "R2" in report["unverified_requirements"]


# ---------------------------------------------------------------------------
# T4  SysML 1.6 vs 1.7 namespace
# ---------------------------------------------------------------------------

class TestNamespaces:
    """Export with 1.6 and 1.7 produce distinct namespace URIs; import auto-detects."""

    def _minimal_matrix(self) -> TraceabilityMatrix:
        return TraceabilityMatrix(
            [Requirement("R1", "Req", satisfied_by=["D1"], verified_by=["T1"])],
            [DesignElement("D1", "block", "Block1")],
            [TestCase("T1", "Test1", verifies=["R1"])],
        )

    def test_v17_namespace_uri_in_xmi(self, tmp_path):
        matrix = self._minimal_matrix()
        xmi_path = tmp_path / "model_17.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        content = xmi_path.read_text(encoding="utf-8")
        assert _NS_SYSML["1.7"] in content

    def test_v16_namespace_uri_in_xmi(self, tmp_path):
        matrix = self._minimal_matrix()
        xmi_path = tmp_path / "model_16.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.6")
        content = xmi_path.read_text(encoding="utf-8")
        assert _NS_SYSML["1.6"] in content

    def test_v16_vs_v17_namespaces_distinct(self):
        assert _NS_SYSML["1.6"] != _NS_SYSML["1.7"]

    def test_v17_does_not_contain_v16_namespace(self, tmp_path):
        matrix = self._minimal_matrix()
        xmi_path = tmp_path / "model_17.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        content = xmi_path.read_text(encoding="utf-8")
        # The 1.6 URI must NOT appear in a 1.7 export
        assert _NS_SYSML["1.6"] not in content

    def test_v16_does_not_contain_v17_namespace(self, tmp_path):
        matrix = self._minimal_matrix()
        xmi_path = tmp_path / "model_16.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.6")
        content = xmi_path.read_text(encoding="utf-8")
        assert _NS_SYSML["1.7"] not in content

    def test_import_autodetects_v17(self, tmp_path):
        matrix = self._minimal_matrix()
        xmi_path = tmp_path / "model_17.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.7")
        restored = import_xmi(xmi_path)
        assert "R1" in restored.requirements

    def test_import_autodetects_v16(self, tmp_path):
        matrix = self._minimal_matrix()
        xmi_path = tmp_path / "model_16.xmi"
        export_xmi(matrix, xmi_path, sysml_version="1.6")
        restored = import_xmi(xmi_path)
        assert "R1" in restored.requirements

    def test_unsupported_version_raises(self):
        with pytest.raises(ValueError, match="Unsupported SysML version"):
            matrix = self._minimal_matrix()
            with tempfile.NamedTemporaryFile(suffix=".xmi", delete=False) as f:
                path = f.name
            try:
                export_xmi(matrix, path, sysml_version="2.0")
            finally:
                if os.path.exists(path):
                    os.unlink(path)


# ---------------------------------------------------------------------------
# Tool spec smoke tests
# ---------------------------------------------------------------------------

class TestToolSpecs:
    def test_coverage_tool_name(self):
        from kerf_plm.sysml_tools import sysml_trace_coverage_spec
        assert sysml_trace_coverage_spec.name == "sysml_trace_coverage"

    def test_export_tool_name(self):
        from kerf_plm.sysml_tools import sysml_export_xmi_spec
        assert sysml_export_xmi_spec.name == "sysml_export_xmi"

    def test_import_tool_name(self):
        from kerf_plm.sysml_tools import sysml_import_xmi_spec
        assert sysml_import_xmi_spec.name == "sysml_import_xmi"

    def test_tools_list_has_three_entries(self):
        from kerf_plm.sysml_tools import TOOLS
        assert len(TOOLS) == 3

    def test_coverage_schema_has_requirements(self):
        from kerf_plm.sysml_tools import sysml_trace_coverage_spec
        assert "requirements" in sysml_trace_coverage_spec.input_schema["required"]
