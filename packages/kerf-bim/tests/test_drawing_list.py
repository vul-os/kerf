"""
test_drawing_list.py — pytest suite for drawing_list.py pure logic.

Tests:
  - 20 architectural sheets auto-number to A-101 … A-120
  - Mixed disciplines: A-1XX architectural, S-2XX structural
  - Validate catches duplicate sheet numbers
  - Validate catches orphaned cross-reference
  - Cross-ref computation returns correct tuples
  - Report dataclass is populated correctly
  - generate_drawing_index_sheet writes a file
  - SheetSpec dimensions_mm returns sensible values
  - preserve_existing scheme skips already-numbered sheets
  - auto_number_sheets raises on unknown scheme
"""
from __future__ import annotations

import os
import sys
import types
import importlib.util

# ── minimal stubs so the module loads without the full Kerf runtime ───────────

def _stub_module(name: str, **attrs) -> types.ModuleType:
    if name in sys.modules:
        # Real module already imported — don't clobber it; just return it.
        return sys.modules[name]
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

# Stub out kerf_chat and kerf_core before importing drawing_list (the tools
# module uses a gated import, so it won't fail if these are absent; we still
# need them in sys.modules to satisfy the 'from' imports at module level in
# drawing_list.py directly — there are none — but the tools module has them.)
_stub_module("kerf_chat")
_stub_module("kerf_chat.tools")
_ToolSpec = type("ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)})
_stub_module(
    "kerf_chat.tools.registry",
    ToolSpec=_ToolSpec,
    err_payload=lambda msg, code: __import__("json").dumps({"error": msg, "code": code}),
    ok_payload=lambda v: __import__("json").dumps(v),
    register=lambda spec, write=False: (lambda fn: fn),
)
_stub_module("kerf_core")
_stub_module("kerf_core.utils")
_stub_module("kerf_core.utils.context", ProjectCtx=type("ProjectCtx", (), {}))

# Now we can import from the package path directly.
_PKG = "packages/kerf-bim/src"
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from kerf_bim.drawing_list import (  # noqa: E402
    SheetSize,
    SheetSpec,
    auto_number_sheets,
    compute_cross_references,
    compute_drawing_list_report,
    generate_drawing_index_sheet,
    validate_drawing_list,
)

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_arch_sheets(n: int) -> list[SheetSpec]:
    return [SheetSpec(title=f"Floor Plan Level {i+1}", discipline="architectural") for i in range(n)]


def _make_struct_sheets(n: int) -> list[SheetSpec]:
    return [SheetSpec(title=f"Structural Plan Level {i+1}", discipline="structural") for i in range(n)]


# ── 1. 20 architectural sheets auto-number to A-101 … A-120 ──────────────────

class TestAutoNumberArchitectural20:
    def test_count(self):
        sheets = _make_arch_sheets(20)
        result = auto_number_sheets(sheets)
        assert len(result) == 20

    def test_first(self):
        sheets = _make_arch_sheets(20)
        auto_number_sheets(sheets)
        assert sheets[0].sheet_number == "A-101"

    def test_last(self):
        sheets = _make_arch_sheets(20)
        auto_number_sheets(sheets)
        assert sheets[19].sheet_number == "A-120"

    def test_sequential(self):
        sheets = _make_arch_sheets(20)
        auto_number_sheets(sheets)
        for i, sheet in enumerate(sheets):
            expected = f"A-{101 + i:03d}"
            assert sheet.sheet_number == expected, (
                f"Expected {expected}, got {sheet.sheet_number}"
            )

    def test_no_duplicates(self):
        sheets = _make_arch_sheets(20)
        auto_number_sheets(sheets)
        numbers = [s.sheet_number for s in sheets]
        assert len(numbers) == len(set(numbers))


# ── 2. Mixed disciplines: A-1XX arch, S-2XX structural ───────────────────────

class TestAutoNumberMixedDisciplines:
    def test_arch_prefix(self):
        sheets = _make_arch_sheets(3)
        auto_number_sheets(sheets)
        for s in sheets:
            assert s.sheet_number.startswith("A-")

    def test_struct_prefix(self):
        sheets = _make_struct_sheets(3)
        auto_number_sheets(sheets)
        for s in sheets:
            assert s.sheet_number.startswith("S-")

    def test_arch_series_100(self):
        sheets = _make_arch_sheets(3)
        auto_number_sheets(sheets)
        assert sheets[0].sheet_number == "A-101"
        assert sheets[2].sheet_number == "A-103"

    def test_struct_series_200(self):
        sheets = _make_struct_sheets(3)
        auto_number_sheets(sheets)
        assert sheets[0].sheet_number == "S-201"
        assert sheets[2].sheet_number == "S-203"

    def test_mixed_list_independent_counters(self):
        sheets = [
            SheetSpec(title="A1", discipline="architectural"),
            SheetSpec(title="S1", discipline="structural"),
            SheetSpec(title="A2", discipline="architectural"),
            SheetSpec(title="S2", discipline="structural"),
        ]
        auto_number_sheets(sheets)
        arch = [s for s in sheets if s.discipline == "architectural"]
        struct = [s for s in sheets if s.discipline == "structural"]
        assert arch[0].sheet_number == "A-101"
        assert arch[1].sheet_number == "A-102"
        assert struct[0].sheet_number == "S-201"
        assert struct[1].sheet_number == "S-202"

    def test_mep_series(self):
        sheets = [SheetSpec(title="MEP Plan", discipline="mep") for _ in range(2)]
        auto_number_sheets(sheets)
        assert sheets[0].sheet_number == "M-301"
        assert sheets[1].sheet_number == "M-302"

    def test_civil_series(self):
        sheets = [SheetSpec(title="Site Plan", discipline="civil") for _ in range(2)]
        auto_number_sheets(sheets)
        assert sheets[0].sheet_number == "C-601"

    def test_interior_series(self):
        sheets = [SheetSpec(title="Interior Elevation", discipline="interior") for _ in range(2)]
        auto_number_sheets(sheets)
        assert sheets[0].sheet_number == "I-701"


# ── 3. Validate catches duplicate sheet numbers ───────────────────────────────

class TestValidateDuplicates:
    def test_clean_set_passes(self):
        sheets = _make_arch_sheets(5)
        auto_number_sheets(sheets)
        errors = validate_drawing_list(sheets)
        assert errors == []

    def test_duplicate_caught(self):
        sheets = _make_arch_sheets(3)
        auto_number_sheets(sheets)
        # Force a duplicate.
        sheets[2].sheet_number = sheets[0].sheet_number
        errors = validate_drawing_list(sheets)
        assert any("Duplicate" in e or "duplicate" in e for e in errors)

    def test_duplicate_message_includes_number(self):
        sheets = _make_arch_sheets(2)
        auto_number_sheets(sheets)
        sheets[1].sheet_number = sheets[0].sheet_number
        errors = validate_drawing_list(sheets)
        assert any(sheets[0].sheet_number in e for e in errors)

    def test_missing_sheet_number_caught(self):
        sheets = [SheetSpec(title="Cover Sheet", discipline="architectural")]
        # sheet_number is blank (default)
        errors = validate_drawing_list(sheets)
        assert any("sheet_number" in e or "no sheet" in e.lower() for e in errors)

    def test_missing_title_caught(self):
        sheets = [SheetSpec(title="", discipline="architectural", sheet_number="A-001")]
        errors = validate_drawing_list(sheets)
        assert any("title" in e.lower() for e in errors)


# ── 4. Cross-ref detects orphaned marker ─────────────────────────────────────

class TestOrphanCrossRef:
    def _sheets_with_xref(self, target: str) -> list[SheetSpec]:
        """Return a set where sheet A-101 references target via a viewport."""
        sheets = [
            SheetSpec(
                title="Floor Plan",
                discipline="architectural",
                sheet_number="A-101",
                viewports=[{"view_ref": f"1/{target}", "origin": [0, 0]}],
            ),
        ]
        return sheets

    def test_valid_ref_no_error(self):
        sheets = self._sheets_with_xref("A-101")  # self-reference is valid
        errors = validate_drawing_list(sheets)
        orphan_errors = [e for e in errors if "missing sheet" in e.lower() or "orphan" in e.lower()]
        # A-101 referencing itself is fine.
        assert orphan_errors == []

    def test_orphan_ref_caught(self):
        sheets = self._sheets_with_xref("A-999")  # A-999 doesn't exist
        errors = validate_drawing_list(sheets)
        assert any("A-999" in e for e in errors), errors

    def test_orphan_message_includes_from_sheet(self):
        sheets = self._sheets_with_xref("S-999")
        errors = validate_drawing_list(sheets)
        assert any("A-101" in e for e in errors), errors


# ── 5. Cross-reference computation ───────────────────────────────────────────

class TestComputeCrossReferences:
    def test_empty(self):
        sheets = _make_arch_sheets(3)
        auto_number_sheets(sheets)
        refs = compute_cross_references(sheets)
        assert refs == []

    def test_single_ref(self):
        sheets = [
            SheetSpec(
                title="Floor Plan",
                discipline="architectural",
                sheet_number="A-101",
                viewports=[{"view_ref": "1/A-301", "origin": [0, 0]}],
            ),
            SheetSpec(
                title="Detail Sheet",
                discipline="architectural",
                sheet_number="A-301",
            ),
        ]
        refs = compute_cross_references(sheets)
        assert len(refs) == 1
        from_sheet, to_sheet, marker = refs[0]
        assert from_sheet == "A-101"
        assert to_sheet   == "A-301"
        assert marker     == "1/A-301"

    def test_orphan_not_included(self):
        sheets = [
            SheetSpec(
                title="Floor Plan",
                discipline="architectural",
                sheet_number="A-101",
                viewports=[{"view_ref": "1/A-999", "origin": [0, 0]}],
            ),
        ]
        refs = compute_cross_references(sheets)
        assert refs == []  # orphan excluded from resolved list


# ── 6. DrawingListReport ──────────────────────────────────────────────────────

class TestDrawingListReport:
    def test_total_count(self):
        sheets = _make_arch_sheets(5) + _make_struct_sheets(3)
        auto_number_sheets(sheets)
        report = compute_drawing_list_report(sheets)
        assert report.total_sheets == 8

    def test_by_discipline(self):
        sheets = _make_arch_sheets(5) + _make_struct_sheets(3)
        auto_number_sheets(sheets)
        report = compute_drawing_list_report(sheets)
        assert report.sheets_by_discipline["architectural"] == 5
        assert report.sheets_by_discipline["structural"]    == 3

    def test_summary_table_length(self):
        sheets = _make_arch_sheets(4)
        auto_number_sheets(sheets)
        report = compute_drawing_list_report(sheets)
        assert len(report.sheet_summary_table) == 4

    def test_summary_table_row_shape(self):
        sheets = _make_arch_sheets(1)
        auto_number_sheets(sheets)
        report = compute_drawing_list_report(sheets)
        row = report.sheet_summary_table[0]
        # (sheet_number, title, discipline, sheet_size, scale)
        assert len(row) == 5
        assert row[0] == "A-101"
        assert row[2] == "architectural"

    def test_honest_caveat_present(self):
        sheets = _make_arch_sheets(1)
        auto_number_sheets(sheets)
        report = compute_drawing_list_report(sheets)
        assert len(report.honest_caveat) > 20


# ── 7. generate_drawing_index_sheet ──────────────────────────────────────────

class TestGenerateDrawingIndex:
    def test_returns_path(self):
        sheets = _make_arch_sheets(3)
        auto_number_sheets(sheets)
        path = generate_drawing_index_sheet(sheets, output_format="dxf")
        assert os.path.isfile(path), f"File not found: {path}"
        os.unlink(path)

    def test_file_contains_header(self):
        sheets = _make_arch_sheets(2)
        auto_number_sheets(sheets)
        path = generate_drawing_index_sheet(sheets, output_format="dxf")
        content = open(path).read()
        os.unlink(path)
        assert "DRAWING INDEX" in content

    def test_file_contains_sheet_number(self):
        sheets = _make_arch_sheets(1)
        auto_number_sheets(sheets)
        path = generate_drawing_index_sheet(sheets)
        content = open(path).read()
        os.unlink(path)
        assert "A-101" in content

    def test_pdf_suffix(self):
        sheets = _make_arch_sheets(1)
        auto_number_sheets(sheets)
        path = generate_drawing_index_sheet(sheets, output_format="pdf")
        assert path.endswith(".pdf")
        os.unlink(path)

    def test_bad_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            generate_drawing_index_sheet([], output_format="png")


# ── 8. SheetSpec dimensions_mm ────────────────────────────────────────────────

class TestSheetSpecDimensions:
    def test_a1(self):
        s = SheetSpec(title="X", discipline="architectural", sheet_size=SheetSize.A1)
        assert s.dimensions_mm == (841, 594)

    def test_a0(self):
        s = SheetSpec(title="X", discipline="architectural", sheet_size=SheetSize.A0)
        assert s.dimensions_mm == (1189, 841)

    def test_ansi_d(self):
        s = SheetSpec(title="X", discipline="architectural", sheet_size=SheetSize.ANSI_D)
        assert s.dimensions_mm == (864, 559)


# ── 9. preserve_existing scheme ──────────────────────────────────────────────

class TestPreserveExistingScheme:
    def test_pre_numbered_not_overwritten(self):
        sheets = [
            SheetSpec(title="Cover", discipline="architectural", sheet_number="A-001"),
            SheetSpec(title="Plans", discipline="architectural"),
        ]
        auto_number_sheets(sheets, scheme="preserve_existing")
        assert sheets[0].sheet_number == "A-001"   # preserved
        assert sheets[1].sheet_number == "A-101"   # newly assigned

    def test_unknown_scheme_raises(self):
        with pytest.raises(ValueError, match="Unknown scheme"):
            auto_number_sheets([], scheme="nonsense")
