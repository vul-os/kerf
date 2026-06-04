"""
Tests for kerf_dental.lab_workflow — Wave 11B: 3shape parity

Tests:
- DentalCase model and status
- create_milling_export produces STL files
- export_articulator_setup produces JSON + STL files
- case_status_report aggregates correctly

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

import numpy as np
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_dental.lab_workflow import (
    DentalCase,
    CaseExport,
    create_milling_export,
    export_articulator_setup,
    case_status_report,
    _mesh_to_binary_stl,
)
from kerf_dental.intraoral_scan import IntraoralScan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_iso() -> str:
    return date.today().isoformat()


def _future_iso(days: int = 7) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _past_iso(days: int = 3) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _make_case(
    case_id: str = "C001",
    case_type: str = "crown",
    status: str = "received",
    due: str | None = None,
) -> DentalCase:
    return DentalCase(
        case_id=case_id,
        patient_id_hashed="sha256:abc123",
        dentist_name="Dr Smith",
        lab_name="Apex Lab",
        case_type=case_type,
        received_date_iso=_today_iso(),
        due_date_iso=due or _future_iso(5),
        status=status,
    )


def _simple_mesh() -> tuple:
    verts = np.array([
        [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
        [0, 0, 5], [10, 0, 5], [10, 10, 5], [0, 10, 5],
    ], dtype=float)
    tris = np.array([
        [0,2,1],[0,3,2],
        [4,5,6],[4,6,7],
        [0,1,5],[0,5,4],
        [1,2,6],[1,6,5],
        [2,3,7],[2,7,6],
        [3,0,4],[3,4,7],
    ], dtype=int)
    return verts, tris


class _MockCrownDesign:
    """Mock CrownDesign for milling export testing."""
    def __init__(self):
        self.outer_surface_mesh = _simple_mesh()
        self.intaglio_surface_mesh = _simple_mesh()
        self.spec = type("Spec", (), {"tooth_number": type("TN", (), {"fdi": "36"})()})()


class _MockDentureDesign:
    def __init__(self):
        self.base_mesh = _simple_mesh()
        self.teeth = [_simple_mesh(), _simple_mesh()]
        self.clasps = []


# ===========================================================================
# DentalCase
# ===========================================================================

class TestDentalCase:
    def test_valid_case_construction(self):
        c = _make_case()
        assert c.case_id == "C001"
        assert c.case_type == "crown"

    def test_invalid_case_type_raises(self):
        with pytest.raises(ValueError):
            DentalCase(
                case_id="C001",
                patient_id_hashed="hash",
                dentist_name="Dr X",
                lab_name="Lab Y",
                case_type="filling",  # invalid
                received_date_iso=_today_iso(),
                due_date_iso=_future_iso(),
                status="received",
            )

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError):
            DentalCase(
                case_id="C001",
                patient_id_hashed="hash",
                dentist_name="Dr X",
                lab_name="Lab Y",
                case_type="crown",
                received_date_iso=_today_iso(),
                due_date_iso=_future_iso(),
                status="lost",  # invalid
            )

    def test_not_overdue_when_future(self):
        c = _make_case(due=_future_iso(5))
        assert not c.is_overdue

    def test_overdue_when_past(self):
        c = _make_case(due=_past_iso(2))
        assert c.is_overdue

    def test_shipped_not_overdue_even_if_past(self):
        c = DentalCase(
            case_id="C001",
            patient_id_hashed="hash",
            dentist_name="Dr X",
            lab_name="Lab Y",
            case_type="crown",
            received_date_iso=_today_iso(),
            due_date_iso=_past_iso(2),
            status="shipped",
        )
        assert not c.is_overdue

    def test_days_until_due_future(self):
        c = _make_case(due=_future_iso(5))
        assert c.days_until_due >= 4

    def test_days_until_due_past(self):
        c = _make_case(due=_past_iso(3), status="designing")
        assert c.days_until_due <= -2


# ===========================================================================
# create_milling_export
# ===========================================================================

class TestCreateMillingExport:
    def test_stl_export_from_crown_design(self):
        design = _MockCrownDesign()
        export = create_milling_export(design, mill_format="STL")
        assert isinstance(export, CaseExport)
        assert export.file_count > 0

    def test_stl_files_non_empty(self):
        design = _MockCrownDesign()
        export = create_milling_export(design, mill_format="STL")
        for name, content in export.files.items():
            assert name.endswith(".stl"), f"Expected .stl file, got {name}"
            assert len(content) > 84, f"STL file {name} too small"

    def test_stl_binary_header(self):
        design = _MockCrownDesign()
        export = create_milling_export(design, mill_format="STL")
        for content in export.files.values():
            # Binary STL: first 80 bytes are header, then 4-byte triangle count
            import struct
            n_tris = struct.unpack_from("<I", content, 80)[0]
            expected_size = 84 + 50 * n_tris
            assert len(content) == expected_size

    def test_ply_export(self):
        design = _MockDentureDesign()
        export = create_milling_export(design, mill_format="PLY")
        for name, content in export.files.items():
            assert name.endswith(".ply")
            assert b"ply" in content

    def test_invalid_format_raises(self):
        design = _MockCrownDesign()
        with pytest.raises(ValueError):
            create_milling_export(design, mill_format="OBJ")

    def test_file_format_stored(self):
        design = _MockCrownDesign()
        export = create_milling_export(design, mill_format="STL")
        assert export.file_format == "stl"

    def test_total_size_positive(self):
        design = _MockCrownDesign()
        export = create_milling_export(design)
        assert export.total_size_bytes > 0


# ===========================================================================
# export_articulator_setup
# ===========================================================================

class TestExportArticulatorSetup:
    def _make_scan(self, arch: str = "maxillary") -> IntraoralScan:
        verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
        tris = np.array([[0, 1, 2]], dtype=int)
        return IntraoralScan(verts, tris, "Trios 4", arch, "2024-01-01")

    def test_returns_case_export(self):
        max_s = self._make_scan("maxillary")
        man_s = self._make_scan("mandibular")
        T = np.eye(4)
        export = export_articulator_setup(max_s, man_s, T)
        assert isinstance(export, CaseExport)

    def test_json_file_in_export(self):
        max_s = self._make_scan()
        man_s = self._make_scan("mandibular")
        export = export_articulator_setup(max_s, man_s, np.eye(4))
        assert "articulator_setup.json" in export.files

    def test_json_contains_transform(self):
        max_s = self._make_scan()
        man_s = self._make_scan("mandibular")
        T = np.eye(4)
        T[0, 3] = 5.0  # known translation
        export = export_articulator_setup(max_s, man_s, T)
        setup = json.loads(export.files["articulator_setup.json"].decode())
        assert setup["transform_mandibular_to_maxillary"][0][3] == pytest.approx(5.0)

    def test_invalid_transform_shape_raises(self):
        max_s = self._make_scan()
        man_s = self._make_scan("mandibular")
        with pytest.raises(ValueError):
            export_articulator_setup(max_s, man_s, np.eye(3))  # wrong shape


# ===========================================================================
# case_status_report
# ===========================================================================

class TestCaseStatusReport:
    def test_total_count(self):
        cases = [_make_case(f"C{i:03d}") for i in range(5)]
        report = case_status_report(cases)
        assert report["total"] == 5

    def test_by_status_counts(self):
        cases = [
            _make_case("C001", status="received"),
            _make_case("C002", status="received"),
            _make_case("C003", status="milling"),
        ]
        report = case_status_report(cases)
        assert report["by_status"]["received"] == 2
        assert report["by_status"]["milling"] == 1

    def test_overdue_detection(self):
        cases = [
            _make_case("C001", due=_past_iso(2), status="designing"),
            _make_case("C002", due=_future_iso(5)),
        ]
        report = case_status_report(cases)
        assert report["overdue"] == 1
        assert "C001" in report["overdue_cases"]

    def test_throughput_by_dentist(self):
        c1 = DentalCase("C001", "h1", "Dr A", "Lab X", "crown",
                         _today_iso(), _future_iso(3), "delivered")
        c2 = DentalCase("C002", "h2", "Dr A", "Lab X", "bridge",
                         _today_iso(), _future_iso(2), "shipped")
        c3 = DentalCase("C003", "h3", "Dr B", "Lab X", "crown",
                         _today_iso(), _future_iso(1), "received")
        report = case_status_report([c1, c2, c3])
        assert report["throughput_by_dentist"]["Dr A"] == 2
        assert report["throughput_by_dentist"].get("Dr B", 0) == 0

    def test_by_type_counts(self):
        cases = [
            _make_case("C001", case_type="crown"),
            _make_case("C002", case_type="bridge"),
            _make_case("C003", case_type="crown"),
        ]
        report = case_status_report(cases)
        assert report["by_type"]["crown"] == 2
        assert report["by_type"]["bridge"] == 1

    def test_empty_cases_returns_zero_total(self):
        report = case_status_report([])
        assert report["total"] == 0
