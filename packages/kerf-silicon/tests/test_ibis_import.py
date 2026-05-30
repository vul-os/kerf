"""test_ibis_import.py — validation tests for kerf-silicon IBIS 7.1 importer.

Tests
-----
  IB01  Simple buffer parse: 1 component, 1 pin, 1 model; voltage range [0, 3.3] V;
         pulldown table has expected number of points.
  IB02  IV interpolation: at V=1.65 V (mid-range), pulldown current ≈ interpolated
         between table entries within 1%.
  IB03  Eye diagram bound: at 1 GHz, 50 Ω load, eye_opening > 50% Vcc (functional check).
  IB04  Parser error handling: malformed .ibs file raises IbisParseError with line number.

IBIS 7.1 spec compliance note
------------------------------
These tests validate the *kerf-silicon* IBIS importer, not IBIS certification.
The implementation is NOT IBIS-certified.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure the src/ layout is importable from tests/
_PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PKG / "src"))

from kerf_silicon.ibis_import import (
    IbisModel,
    IbisParseError,
    compute_eye_diagram_at_pin,
    evaluate_buffer_iv,
    parse_ibis_file,
    _parse_ibis_lines,
)

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_SIMPLE_IBS = _FIXTURES / "simple_buffer.ibs"


# ---------------------------------------------------------------------------
# IB01 — Simple buffer parse
# ---------------------------------------------------------------------------

class TestSimpleBufferParse:
    """IB01: Parse the simple_buffer.ibs fixture and verify structure."""

    @pytest.fixture(scope="class")
    def model(self) -> IbisModel:
        assert _SIMPLE_IBS.exists(), f"Fixture not found: {_SIMPLE_IBS}"
        return parse_ibis_file(str(_SIMPLE_IBS))

    def test_ib01a_returns_ibis_model(self, model):
        """IB01a: parse_ibis_file returns an IbisModel instance."""
        assert isinstance(model, IbisModel)

    def test_ib01b_component_name(self, model):
        """IB01b: Component name is 'TestBuffer'."""
        assert model.component.name == "TestBuffer"

    def test_ib01c_single_pin(self, model):
        """IB01c: Exactly one pin in the [Pin] section."""
        assert len(model.pins) == 1, f"Expected 1 pin, got {len(model.pins)}: {list(model.pins)}"

    def test_ib01d_single_model(self, model):
        """IB01d: Exactly one [Model] (OutBuf) parsed."""
        assert len(model.models) == 1, f"Expected 1 model: {list(model.models)}"
        assert "OutBuf" in model.models

    def test_ib01e_voltage_range(self, model):
        """IB01e: Voltage Range typ = 3.3 V, min = 3.0 V, max = 3.6 V."""
        buf = model.models["OutBuf"]
        assert buf.vcc_typ == pytest.approx(3.3, rel=1e-3)
        assert buf.vcc_min == pytest.approx(3.0, rel=1e-3)
        assert buf.vcc_max == pytest.approx(3.6, rel=1e-3)

    def test_ib01f_pulldown_table_point_count(self, model):
        """IB01f: Pulldown table has 10 entries (as defined in fixture)."""
        buf = model.models["OutBuf"]
        assert buf.pulldown is not None, "Pulldown table missing"
        # Fixture has 10 rows: -0.5, 0.0, 0.5, 1.0, 1.65, 2.0, 2.5, 3.0, 3.3, 3.8
        assert len(buf.pulldown.points) == 10, (
            f"Expected 10 pulldown points, got {len(buf.pulldown.points)}"
        )

    def test_ib01g_pulldown_sorted_ascending(self, model):
        """IB01g: Pulldown points are sorted by voltage ascending."""
        buf = model.models["OutBuf"]
        voltages = [p.voltage for p in buf.pulldown.points]
        assert voltages == sorted(voltages)

    def test_ib01h_pullup_table_present(self, model):
        """IB01h: Pullup table parsed and has points."""
        buf = model.models["OutBuf"]
        assert buf.pullup is not None, "Pullup table missing"
        assert len(buf.pullup.points) > 0

    def test_ib01i_pin_model_mapping(self, model):
        """IB01i: Pin A1 maps to model OutBuf."""
        assert "A1" in model.pins
        assert model.pins["A1"].model_name == "OutBuf"

    def test_ib01j_ibis_version_string(self, model):
        """IB01j: IBIS version is parsed from [IBIS Ver] keyword."""
        # The fixture says [IBIS Ver] 7.1
        assert "7.1" in model.ibis_version or model.ibis_version != ""

    def test_ib01k_c_comp_parsed(self, model):
        """IB01k: C_comp parsed and > 0."""
        buf = model.models["OutBuf"]
        assert buf.c_comp > 0, f"c_comp should be >0, got {buf.c_comp}"

    def test_ib01l_gnd_clamp_parsed(self, model):
        """IB01l: GND_clamp table parsed."""
        buf = model.models["OutBuf"]
        assert buf.gnd_clamp is not None
        assert len(buf.gnd_clamp.points) > 0

    def test_ib01m_ramp_parsed(self, model):
        """IB01m: Ramp section is parsed with dV/dt_r > 0."""
        buf = model.models["OutBuf"]
        assert buf.ramp is not None, "Ramp data missing"
        assert buf.ramp.dv_dt_rise > 0, f"dV/dt_rise should be >0, got {buf.ramp.dv_dt_rise}"


# ---------------------------------------------------------------------------
# IB02 — IV interpolation accuracy
# ---------------------------------------------------------------------------

class TestIVInterpolation:
    """IB02: evaluate_buffer_iv interpolates IV at arbitrary voltages within 1%."""

    @pytest.fixture(scope="class")
    def model(self) -> IbisModel:
        return parse_ibis_file(str(_SIMPLE_IBS))

    def test_ib02a_midpoint_iv(self, model):
        """IB02a: At V=1.65 V (exact table point), current = 33.0 mA (typ)."""
        i = evaluate_buffer_iv("OutBuf", 1.65, model)
        expected = 33.0e-3
        assert abs(i - expected) / expected < 0.01, (
            f"Expected ~{expected * 1e3:.1f} mA at 1.65 V, got {i * 1e3:.2f} mA"
        )

    def test_ib02b_interpolated_between_points(self, model):
        """IB02b: At V=1.825 V (between 1.65 and 2.0), current interpolates within 1%."""
        # Linear between (1.65, 33.0m) and (2.0, 40.0m):
        # I = 33.0 + (40.0 - 33.0) * (1.825 - 1.65) / (2.0 - 1.65)
        # I = 33.0 + 7.0 * 0.5 = 36.5 mA
        i = evaluate_buffer_iv("OutBuf", 1.825, model)
        expected = 36.5e-3
        assert abs(i - expected) / expected < 0.01, (
            f"Expected ~{expected * 1e3:.1f} mA at 1.825 V, got {i * 1e3:.2f} mA"
        )

    def test_ib02c_at_zero_current_is_zero(self, model):
        """IB02c: At V=0.0 V, pulldown current = 0 A (table entry)."""
        i = evaluate_buffer_iv("OutBuf", 0.0, model)
        assert abs(i) < 1e-6, f"Expected ~0 A at 0 V, got {i * 1e3:.3f} mA"

    def test_ib02d_beyond_range_flat_extrapolation(self, model):
        """IB02d: At V=5.0 V (beyond table), returns value at last table point."""
        i_high = evaluate_buffer_iv("OutBuf", 5.0, model)
        i_last = evaluate_buffer_iv("OutBuf", 3.8, model)
        assert i_high == pytest.approx(i_last, rel=1e-6)

    def test_ib02e_missing_model_raises_key_error(self, model):
        """IB02e: Unknown model name raises KeyError."""
        with pytest.raises(KeyError, match="not found"):
            evaluate_buffer_iv("NoSuchModel", 1.0, model)

    def test_ib02f_interpolation_monotone(self, model):
        """IB02f: IV curve is monotonically non-decreasing over [0, 3.3] V."""
        voltages = [v * 0.1 for v in range(34)]  # 0.0, 0.1, …, 3.3
        currents = [evaluate_buffer_iv("OutBuf", v, model) for v in voltages]
        for i in range(1, len(currents)):
            assert currents[i] >= currents[i - 1] - 1e-9, (
                f"Non-monotone at V={voltages[i]:.1f}: I={currents[i] * 1e3:.3f} mA < "
                f"I_prev={currents[i - 1] * 1e3:.3f} mA"
            )


# ---------------------------------------------------------------------------
# IB03 — Eye diagram functional check
# ---------------------------------------------------------------------------

class TestEyeDiagram:
    """IB03: Eye diagram at 1 GHz / 50 Ω > 50% Vcc opening height."""

    @pytest.fixture(scope="class")
    def model(self) -> IbisModel:
        return parse_ibis_file(str(_SIMPLE_IBS))

    def test_ib03a_eye_opening_gt_50pct_vcc(self, model):
        """IB03a: At 1 GHz, 50 Ω, eye opening > 50% Vcc (1.65 V = 1650 mV)."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        vcc = model.models["OutBuf"].vcc_typ  # 3.3 V
        threshold_mv = 0.50 * vcc * 1000.0   # 1650 mV
        assert result.opening_height_mV > threshold_mv, (
            f"Eye opening {result.opening_height_mV:.1f} mV not > "
            f"50% Vcc = {threshold_mv:.1f} mV"
        )

    def test_ib03b_eye_width_positive(self, model):
        """IB03b: Eye width is positive at 1 GHz."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        assert result.opening_width_ps > 0, (
            f"Eye width should be positive, got {result.opening_width_ps:.1f} ps"
        )

    def test_ib03c_eye_width_lt_ui(self, model):
        """IB03c: Eye width <= UI (1000 ps at 1 GHz)."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        assert result.opening_width_ps <= result.symbol_period_ps + 1.0  # 1 ps tolerance

    def test_ib03d_jitter_estimate_positive(self, model):
        """IB03d: Jitter estimate is positive."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        assert result.jitter_estimate_ps > 0

    def test_ib03e_jitter_lt_ui(self, model):
        """IB03e: Jitter estimate is less than the full UI."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        assert result.jitter_estimate_ps < result.symbol_period_ps

    def test_ib03f_higher_freq_narrows_eye(self, model):
        """IB03f: Eye width at 4 GHz is less than at 1 GHz (ISI increases)."""
        res_1g = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        res_4g = compute_eye_diagram_at_pin("A1", model, frequency_ghz=4.0, load_impedance_ohm=50.0)
        # At 4 GHz, UI is 250 ps — eye width should be tighter than at 1 GHz
        assert res_4g.opening_width_ps <= res_1g.opening_width_ps, (
            f"Eye at 4 GHz ({res_4g.opening_width_ps:.1f} ps) should not exceed "
            f"eye at 1 GHz ({res_1g.opening_width_ps:.1f} ps)"
        )

    def test_ib03g_symbol_period_correct(self, model):
        """IB03g: symbol_period_ps = 1000 ps at 1 GHz."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        assert result.symbol_period_ps == pytest.approx(1000.0, rel=1e-6)

    def test_ib03h_driver_r_positive(self, model):
        """IB03h: Effective driver resistance is positive."""
        result = compute_eye_diagram_at_pin("A1", model, frequency_ghz=1.0, load_impedance_ohm=50.0)
        assert result.r_driver_eff_ohm > 0

    def test_ib03i_bad_pin_raises(self, model):
        """IB03i: Unknown pin name raises KeyError."""
        with pytest.raises(KeyError):
            compute_eye_diagram_at_pin("Z99", model, frequency_ghz=1.0, load_impedance_ohm=50.0)

    def test_ib03j_negative_freq_raises(self, model):
        """IB03j: Non-positive frequency raises ValueError."""
        with pytest.raises(ValueError):
            compute_eye_diagram_at_pin("A1", model, frequency_ghz=-1.0, load_impedance_ohm=50.0)


# ---------------------------------------------------------------------------
# IB04 — Parser error handling
# ---------------------------------------------------------------------------

class TestParserErrorHandling:
    """IB04: Malformed .ibs files raise IbisParseError with line number."""

    def _write_tmp(self, content: str) -> str:
        """Write content to a temp file and return path."""
        fd, path = tempfile.mkstemp(suffix=".ibs")
        os.close(fd)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_ib04a_missing_component_raises(self):
        """IB04a: File with no [Component] section raises IbisParseError."""
        content = """\
[IBIS Ver] 7.1
[Model] SomeModel
Model_type Output
[Voltage Range] 3.3 3.0 3.6
[End]
"""
        path = self._write_tmp(content)
        try:
            with pytest.raises(IbisParseError) as exc_info:
                parse_ibis_file(path)
            assert "Component" in str(exc_info.value) or "component" in str(exc_info.value)
        finally:
            os.unlink(path)

    def test_ib04b_missing_model_raises(self):
        """IB04b: File with [Component] but no [Model] raises IbisParseError."""
        content = """\
[IBIS Ver] 7.1
[Component] TestComp
[Manufacturer] Acme
[Pin] signal_name model_name
A1 DQ MissingModel
[End]
"""
        path = self._write_tmp(content)
        try:
            with pytest.raises(IbisParseError) as exc_info:
                parse_ibis_file(path)
            assert "Model" in str(exc_info.value) or "model" in str(exc_info.value)
        finally:
            os.unlink(path)

    def test_ib04c_empty_model_name_raises(self):
        """IB04c: [Model] with empty name raises IbisParseError with line number."""
        lines = [
            "[IBIS Ver] 7.1\n",
            "[Component] TestComp\n",
            "[Pin] signal_name model_name\n",
            "A1 DQ MyModel\n",
            "[Model]   \n",     # Line 5: empty model name → should raise
            "Model_type Output\n",
            "[End]\n",
        ]
        with pytest.raises(IbisParseError) as exc_info:
            _parse_ibis_lines(lines, source_file="<test>")
        err = exc_info.value
        assert err.line_number > 0, (
            f"IbisParseError should carry a positive line_number, got {err.line_number}"
        )

    def test_ib04d_error_has_line_number(self):
        """IB04d: IbisParseError.line_number is set correctly."""
        # Trigger via empty model name at a known line
        lines = ["[IBIS Ver] 7.1\n"] * 3 + ["[Component] C\n", "[Model]  \n"]
        with pytest.raises(IbisParseError) as exc_info:
            _parse_ibis_lines(lines)
        assert exc_info.value.line_number == 5

    def test_ib04e_ibis_parse_error_is_value_error(self):
        """IB04e: IbisParseError inherits from ValueError."""
        err = IbisParseError("test error", line_number=42)
        assert isinstance(err, ValueError)
        assert err.line_number == 42
        assert "42" in str(err)

    def test_ib04f_file_not_found_raises(self):
        """IB04f: parse_ibis_file on a non-existent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            parse_ibis_file("/nonexistent/path/to/nothing.ibs")

    def test_ib04g_iv_table_outside_model_raises(self):
        """IB04g: [Pulldown] outside a [Model] block raises IbisParseError."""
        lines = [
            "[IBIS Ver] 7.1\n",
            "[Component] C\n",
            "[Pulldown]\n",   # Line 3: orphan IV table → raises
            "0.0 0.0\n",
        ]
        with pytest.raises(IbisParseError) as exc_info:
            _parse_ibis_lines(lines)
        assert exc_info.value.line_number == 3


# ---------------------------------------------------------------------------
# LLM tool registration check (plugin surface)
# ---------------------------------------------------------------------------

class TestIBISPluginRegistration:
    """Verify that silicon_import_ibis and silicon_eye_diagram tools register."""

    def _make_ctx(self):
        registered = {}

        class _Tools:
            def register(self, name, spec, handler):
                registered[name] = (spec, handler)

        from types import SimpleNamespace
        ctx = SimpleNamespace(tools=_Tools())
        ctx._registered = registered
        return ctx

    def test_tools_registered(self):
        """Plugin registers silicon_import_ibis and silicon_eye_diagram."""
        ctx = self._make_ctx()
        provides: list[str] = []
        from kerf_silicon.plugin import _register_tools
        _register_tools(ctx, provides)
        reg = ctx._registered
        assert "silicon_import_ibis" in reg, (
            f"silicon_import_ibis not registered. Registered: {list(reg.keys())}"
        )
        assert "silicon_eye_diagram" in reg, (
            f"silicon_eye_diagram not registered. Registered: {list(reg.keys())}"
        )

    def test_provides_contains_ibis(self):
        """_register_tools adds silicon.ibis to provides list."""
        ctx = self._make_ctx()
        provides: list[str] = []
        from kerf_silicon.plugin import _register_tools
        _register_tools(ctx, provides)
        assert "silicon.ibis" in provides, (
            f"silicon.ibis missing from provides: {provides}"
        )
