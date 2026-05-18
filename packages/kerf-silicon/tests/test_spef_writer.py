"""
Tests for kerf_silicon.parasitics.spef_writer

Validates SPEF output against IEEE 1481-1999 structural requirements.
"""
from __future__ import annotations

import os
import sys
import tempfile

# Ensure the source tree is on the path.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_silicon.parasitics.rc_extract import Layout, Wire, extract_rc
from kerf_silicon.parasitics.spef_writer import to_spef


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_report_single_net(
    net: str = "net_A",
    length_um: float = 10.0,
    width_um: float = 0.14,
    layer: str = "met1",
):
    w = Wire(net=net, layer=layer, x0=0.0, y0=0.0, x1=length_um, y1=width_um)
    return extract_rc(Layout(wires=[w]))


def _make_report_two_nets():
    w1 = Wire(net="VDD", layer="met1", x0=0.0, y0=0.0, x1=10.0, y1=0.14)
    w2 = Wire(net="GND", layer="met1", x0=0.0, y0=5.0, x1=20.0, y1=5.14)
    return extract_rc(Layout(wires=[w1, w2]))


def _read_spef(report) -> str:
    """Write report to a temp file and return the content."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".spef", delete=False, encoding="utf-8"
    ) as tf:
        path = tf.name
    try:
        to_spef(report, path)
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Header / format tests
# ---------------------------------------------------------------------------

class TestSpefHeader:
    def test_spef_starts_with_ieee_banner(self):
        """SPEF file must start with the IEEE 1481 banner line."""
        content = _read_spef(_make_report_single_net())
        assert content.startswith('*SPEF "IEEE 1481-1999"')

    def test_spef_contains_design_keyword(self):
        """*DESIGN field must be present."""
        content = _read_spef(_make_report_single_net())
        assert "*DESIGN" in content

    def test_spef_contains_c_unit(self):
        """*C_UNIT declaration must be present."""
        content = _read_spef(_make_report_single_net())
        assert "*C_UNIT" in content

    def test_spef_contains_r_unit(self):
        """*R_UNIT declaration must be present."""
        content = _read_spef(_make_report_single_net())
        assert "*R_UNIT" in content

    def test_spef_contains_divider(self):
        """*DIVIDER keyword must be present."""
        content = _read_spef(_make_report_single_net())
        assert "*DIVIDER" in content


# ---------------------------------------------------------------------------
# Net section tests
# ---------------------------------------------------------------------------

class TestSpefNetSection:
    def test_spef_contains_d_net(self):
        """*D_NET section must be present for each net."""
        content = _read_spef(_make_report_single_net())
        assert "*D_NET" in content

    def test_spef_net_end_marker(self):
        """Each *D_NET block must be closed with *END."""
        content = _read_spef(_make_report_single_net())
        assert "*END" in content

    def test_spef_cap_section_present(self):
        """*CAP section must appear inside each D_NET block."""
        content = _read_spef(_make_report_single_net())
        assert "*CAP" in content

    def test_spef_res_section_present(self):
        """*RES section must appear inside each D_NET block."""
        content = _read_spef(_make_report_single_net())
        assert "*RES" in content

    def test_spef_two_nets_both_in_file(self):
        """Both net names must appear in the SPEF *NAME_MAP."""
        content = _read_spef(_make_report_two_nets())
        assert "VDD" in content
        assert "GND" in content

    def test_spef_two_nets_two_d_net_blocks(self):
        """Two nets → two *D_NET sections."""
        content = _read_spef(_make_report_two_nets())
        assert content.count("*D_NET") == 2

    def test_spef_two_nets_two_end_markers(self):
        """Two nets → two *END markers."""
        content = _read_spef(_make_report_two_nets())
        assert content.count("*END") == 2

    def test_spef_name_map_present(self):
        """*NAME_MAP section must be present."""
        content = _read_spef(_make_report_single_net())
        assert "*NAME_MAP" in content

    def test_spef_name_map_contains_net_name(self):
        """The net name must appear in the *NAME_MAP section."""
        content = _read_spef(_make_report_single_net())
        assert "net_A" in content


# ---------------------------------------------------------------------------
# Empty layout edge case
# ---------------------------------------------------------------------------

class TestSpefEmpty:
    def test_empty_report_file_created(self):
        """to_spef on empty report should create a valid (header-only) file."""
        report = extract_rc(Layout())
        content = _read_spef(report)
        assert '*SPEF "IEEE 1481-1999"' in content
        # No D_NET sections
        assert "*D_NET" not in content

    def test_empty_report_no_end_marker(self):
        """Empty report → no *END marker (no nets to close)."""
        report = extract_rc(Layout())
        content = _read_spef(report)
        assert "*END" not in content


# ---------------------------------------------------------------------------
# File I/O tests
# ---------------------------------------------------------------------------

class TestSpefFileIO:
    def test_to_spef_creates_file(self):
        """to_spef must create the output file."""
        report = _make_report_single_net()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "out.spef")
            assert not os.path.exists(path)
            to_spef(report, path)
            assert os.path.exists(path)

    def test_to_spef_overwrites_existing(self):
        """to_spef must overwrite an existing file."""
        report = _make_report_single_net()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".spef", delete=False
        ) as tf:
            tf.write("old content")
            path = tf.name
        try:
            to_spef(report, path)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            assert "old content" not in content
            assert '*SPEF "IEEE 1481-1999"' in content
        finally:
            os.unlink(path)

    def test_to_spef_accepts_pathlib_path(self):
        """to_spef should accept a pathlib.Path as output_path."""
        import pathlib
        report = _make_report_single_net()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = pathlib.Path(tmpdir) / "out.spef"
            to_spef(report, path)
            content = path.read_text(encoding="utf-8")
            assert '*SPEF "IEEE 1481-1999"' in content


# ---------------------------------------------------------------------------
# Numeric content smoke tests
# ---------------------------------------------------------------------------

class TestSpefNumericContent:
    def test_spef_contains_nonzero_cap_value(self):
        """The *CAP section should contain a numeric value > 0."""
        content = _read_spef(_make_report_single_net(length_um=10.0, width_um=1.0))
        # Find lines after *CAP that contain numeric entries
        lines = content.splitlines()
        cap_values: list[float] = []
        in_cap = False
        for line in lines:
            if line.strip() == "*CAP":
                in_cap = True
                continue
            if line.startswith("*") and in_cap:
                in_cap = False
            if in_cap and line.strip():
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        cap_values.append(float(parts[-1]))
                    except ValueError:
                        pass
        assert any(v > 0 for v in cap_values), "Expected non-zero cap value in SPEF"

    def test_spef_contains_nonzero_res_value(self):
        """The *RES section should contain a numeric value > 0."""
        content = _read_spef(_make_report_single_net())
        lines = content.splitlines()
        res_values: list[float] = []
        in_res = False
        for line in lines:
            if line.strip() == "*RES":
                in_res = True
                continue
            if line.startswith("*") and in_res:
                in_res = False
            if in_res and line.strip():
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        res_values.append(float(parts[-1]))
                    except ValueError:
                        pass
        assert any(v > 0 for v in res_values), "Expected non-zero res value in SPEF"
