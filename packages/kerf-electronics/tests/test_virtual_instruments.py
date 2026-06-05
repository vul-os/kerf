"""
test_virtual_instruments.py — Oracle tests for virtual instrument DSP math.

Test oracle cases:
  - Known sine wave: exact Vpp, frequency, RMS, DC, AC-RMS
  - Step (rise-time): exact 10 %–90 % rise time
  - DC divider: exact node voltages from OP result
  - Multimeter modes
  - Function generator SPICE line generation
  - Probe overlay formatting
  - LLM tool registration (eda_virtual_instrument + eda_probe_nodes)
  - LLM tool arg validation

ALL tests use pure-Python math — no external deps, no ngspice.
"""

from __future__ import annotations

import json
import math
import unittest

# ── DSP measures ─────────────────────────────────────────────────────────────

from kerf_electronics.virtual_instruments.dsp_measures import (
    measure_ac_rms,
    measure_dc,
    measure_frequency,
    measure_rise_time,
    measure_rms,
    measure_vpp,
)

# ── Instrument helpers ────────────────────────────────────────────────────────

from kerf_electronics.virtual_instruments.instruments import (
    function_generator_spec,
    multimeter_measure,
    oscilloscope_measure,
    MultimeterMode,
)

# ── Probe helpers ─────────────────────────────────────────────────────────────

from kerf_electronics.virtual_instruments.probe import (
    format_probe_overlay,
    probe_nodes,
)

# ── LLM tools (import side-effect registers them) ────────────────────────────

import kerf_electronics.virtual_instruments.tools  # noqa: F401

from kerf_electronics._compat import Registry


# ---------------------------------------------------------------------------
# Helpers to build synthetic waveform data
# ---------------------------------------------------------------------------

def _sine_wave(freq_hz: float, amp_v: float, dc_v: float,
               n_cycles: float = 10.0, n_samples: int = 1000):
    """Return (t_list, y_list) for a pure sine wave."""
    period = 1.0 / freq_hz
    tstop = period * n_cycles
    t = [i * tstop / (n_samples - 1) for i in range(n_samples)]
    y = [dc_v + amp_v * math.sin(2 * math.pi * freq_hz * ti) for ti in t]
    return t, y


def _step_wave(tstep_s: float, tr_s: float, v_low: float, v_high: float,
               n_samples: int = 2000):
    """Return (t_list, y_list) for a step from v_low to v_high.

    tstep_s: time at which step starts
    tr_s:    10%–90% rise time (linear ramp)
    """
    swing = v_high - v_low
    t_start_10 = tstep_s
    t_start_90 = tstep_s + tr_s

    tstop = tstep_s + tr_s * 5
    t = [i * tstop / (n_samples - 1) for i in range(n_samples)]
    y = []
    for ti in t:
        if ti < t_start_10:
            y.append(v_low)
        elif ti < t_start_90:
            # Linear ramp from 10 % to 90 % of swing
            frac = (ti - t_start_10) / (t_start_90 - t_start_10)
            y.append(v_low + swing * 0.1 + frac * swing * 0.8)
        else:
            y.append(v_high)
    return t, y


def _list_waveform(name: str, x: list, y: list, kind: str = "V") -> dict:
    """Build a waveform dict in the routes_spice.parse_raw_file format."""
    return {"name": name, "kind": kind, "xUnit": "s", "yUnit": kind, "x": x, "y": y}


# ---------------------------------------------------------------------------
# DSP measure tests — known sine wave
# ---------------------------------------------------------------------------

class TestMeasureVpp(unittest.TestCase):

    def test_sine_vpp_exact(self):
        """Vpp of a 2 V amplitude sine is exactly 4 V."""
        _, y = _sine_wave(1000.0, 2.0, 0.0)
        vpp = measure_vpp(y)
        self.assertAlmostEqual(vpp, 4.0, delta=0.01,
                               msg=f"Expected Vpp≈4.0 V, got {vpp:.4f}")

    def test_dc_signal_zero_vpp(self):
        """A flat DC signal has Vpp = 0."""
        y = [1.5] * 100
        self.assertAlmostEqual(measure_vpp(y), 0.0, places=10)

    def test_raises_on_empty(self):
        with self.assertRaises(ValueError):
            measure_vpp([])


class TestMeasureFrequency(unittest.TestCase):

    def test_1khz_sine(self):
        """Zero-crossing detector returns correct 1 kHz frequency."""
        t, y = _sine_wave(1000.0, 1.0, 0.0)
        freq = measure_frequency(t, y)
        self.assertIsNotNone(freq)
        self.assertAlmostEqual(freq, 1000.0, delta=10.0,
                               msg=f"Expected 1000 Hz, got {freq:.2f} Hz")

    def test_10khz_sine(self):
        t, y = _sine_wave(10000.0, 1.5, 0.0)
        freq = measure_frequency(t, y)
        self.assertIsNotNone(freq)
        self.assertAlmostEqual(freq, 10000.0, delta=100.0)

    def test_dc_returns_none(self):
        """A flat DC signal has no frequency."""
        t = [i * 1e-6 for i in range(100)]
        y = [1.0] * 100
        self.assertIsNone(measure_frequency(t, y))

    def test_raises_on_empty(self):
        with self.assertRaises(ValueError):
            measure_frequency([], [])

    def test_raises_on_length_mismatch(self):
        with self.assertRaises(ValueError):
            measure_frequency([0.0, 1.0], [0.0])


class TestMeasureRiseTime(unittest.TestCase):

    def test_known_rise_time_1us(self):
        """Step with 10 %–90 % rise time of 1 µs is measured correctly."""
        tr = 1e-6  # 1 µs
        t, y = _step_wave(tstep_s=1e-6, tr_s=tr, v_low=0.0, v_high=5.0)
        rt = measure_rise_time(t, y)
        self.assertIsNotNone(rt)
        self.assertAlmostEqual(rt, tr, delta=tr * 0.05,
                               msg=f"Expected rise-time≈{tr*1e6:.1f} µs, got {rt*1e6:.3f} µs")

    def test_known_rise_time_100ns(self):
        """Rise time of 100 ns step."""
        tr = 100e-9
        t, y = _step_wave(tstep_s=100e-9, tr_s=tr, v_low=0.0, v_high=3.3)
        rt = measure_rise_time(t, y)
        self.assertIsNotNone(rt)
        self.assertAlmostEqual(rt, tr, delta=tr * 0.05)

    def test_flat_signal_returns_none(self):
        t = [i * 1e-9 for i in range(200)]
        y = [2.5] * 200
        self.assertIsNone(measure_rise_time(t, y))

    def test_raises_on_empty(self):
        with self.assertRaises(ValueError):
            measure_rise_time([], [])


class TestMeasureRms(unittest.TestCase):

    def test_sine_rms_is_amp_over_sqrt2(self):
        """RMS of a zero-mean sine of amplitude A is A/sqrt(2)."""
        amp = 2.0
        _, y = _sine_wave(1000.0, amp, 0.0, n_samples=10000)
        rms = measure_rms(y)
        expected = amp / math.sqrt(2)
        self.assertAlmostEqual(rms, expected, delta=0.01,
                               msg=f"Expected RMS≈{expected:.4f}, got {rms:.4f}")

    def test_dc_rms_equals_dc_value(self):
        """RMS of a pure DC signal equals the DC value."""
        y = [3.0] * 1000
        self.assertAlmostEqual(measure_rms(y), 3.0, places=10)

    def test_raises_on_empty(self):
        with self.assertRaises(ValueError):
            measure_rms([])


class TestMeasureDc(unittest.TestCase):

    def test_zero_mean_sine(self):
        """Mean of a zero-mean sine is ~0."""
        _, y = _sine_wave(1000.0, 1.0, 0.0, n_samples=10000)
        dc = measure_dc(y)
        self.assertAlmostEqual(dc, 0.0, delta=0.01)

    def test_dc_with_offset(self):
        """Mean of a sine with DC offset returns the offset."""
        offset = 2.5
        _, y = _sine_wave(1000.0, 1.0, offset, n_samples=10000)
        dc = measure_dc(y)
        self.assertAlmostEqual(dc, offset, delta=0.05)

    def test_exact_dc(self):
        y = [4.7] * 100
        self.assertAlmostEqual(measure_dc(y), 4.7, places=10)


class TestMeasureAcRms(unittest.TestCase):

    def test_zero_mean_sine_ac_rms(self):
        """AC RMS of a zero-mean sine equals total RMS."""
        amp = 2.0
        _, y = _sine_wave(1000.0, amp, 0.0, n_samples=10000)
        ac_rms = measure_ac_rms(y)
        expected = amp / math.sqrt(2)
        self.assertAlmostEqual(ac_rms, expected, delta=0.01)

    def test_pure_dc_ac_rms_is_zero(self):
        """AC RMS of a pure DC signal is 0."""
        y = [5.0] * 1000
        self.assertAlmostEqual(measure_ac_rms(y), 0.0, delta=1e-9)

    def test_ac_rms_formula_IEC60469(self):
        """AC_RMS = sqrt(RMS² − DC²) matches direct calculation."""
        amp = 1.0
        dc_val = 2.0
        _, y = _sine_wave(1000.0, amp, dc_val, n_samples=10000)
        ac_rms = measure_ac_rms(y)
        rms = measure_rms(y)
        dc = measure_dc(y)
        expected = math.sqrt(max(0.0, rms ** 2 - dc ** 2))
        self.assertAlmostEqual(ac_rms, expected, places=10)


# ---------------------------------------------------------------------------
# Oscilloscope tests
# ---------------------------------------------------------------------------

class TestOscopeMeasure(unittest.TestCase):

    def _make_waveforms(self):
        t, y = _sine_wave(5000.0, 1.0, 0.0)
        return [_list_waveform("V(out)", t, y)]

    def test_single_channel(self):
        wf = self._make_waveforms()
        result = oscilloscope_measure(wf, ["V(out)"])
        self.assertEqual(len(result.channels), 1)
        ch = result.channels[0]
        self.assertAlmostEqual(ch.vpp, 2.0, delta=0.05)
        self.assertAlmostEqual(ch.frequency_hz, 5000.0, delta=50.0)

    def test_missing_channel_warns(self):
        wf = self._make_waveforms()
        result = oscilloscope_measure(wf, ["V(out)", "V(missing)"])
        self.assertEqual(len(result.channels), 1)
        self.assertTrue(any("V(missing)" in w for w in result.warnings))

    def test_time_axis_extracted(self):
        wf = self._make_waveforms()
        result = oscilloscope_measure(wf, ["V(out)"])
        self.assertIsNotNone(result.time_start_s)
        self.assertIsNotNone(result.time_stop_s)
        self.assertIsNotNone(result.sample_rate_hz)


# ---------------------------------------------------------------------------
# Multimeter tests
# ---------------------------------------------------------------------------

class TestMultimeterMeasure(unittest.TestCase):

    def _make_dc_waveforms(self, v_dc: float):
        """Resistor divider: V(out) = v_dc."""
        t = [i * 1e-6 for i in range(100)]
        y = [v_dc] * 100
        return [_list_waveform("V(out)", t, y)]

    def test_dc_voltage_divider(self):
        """Multimeter DC mode on a resistor-divider node returns exact voltage."""
        # Classic 10k/10k divider from 5 V: Vout = 2.5 V
        vout = 2.5
        wf = self._make_dc_waveforms(vout)
        r = multimeter_measure(wf, "V(out)", MultimeterMode.DC_VOLTAGE)
        self.assertAlmostEqual(r.value, vout, delta=0.001)
        self.assertEqual(r.unit, "V")

    def test_dc_voltage_5k_divider(self):
        """5k / 15k divider from 5V: Vout = 5 * 15/(5+15) = 3.75 V."""
        vout = 3.75
        wf = self._make_dc_waveforms(vout)
        r = multimeter_measure(wf, "V(out)", MultimeterMode.DC_VOLTAGE)
        self.assertAlmostEqual(r.value, vout, delta=0.001)

    def test_ac_rms_mode(self):
        t, y = _sine_wave(1000.0, 2.0, 0.0, n_samples=10000)
        wf = [_list_waveform("V(ac)", t, y)]
        r = multimeter_measure(wf, "V(ac)", MultimeterMode.AC_VOLTAGE_RMS)
        expected = 2.0 / math.sqrt(2)
        self.assertAlmostEqual(r.value, expected, delta=0.05)

    def test_missing_node_returns_warning(self):
        wf = self._make_dc_waveforms(1.0)
        r = multimeter_measure(wf, "V(noexist)", MultimeterMode.DC_VOLTAGE)
        self.assertIsNotNone(r.warning)
        self.assertTrue(math.isnan(r.value))


# ---------------------------------------------------------------------------
# Function generator tests
# ---------------------------------------------------------------------------

class TestFunctionGenerator(unittest.TestCase):

    def test_sine_spice_line(self):
        spec = function_generator_spec("sine", freq_hz=1000.0, amplitude_v=1.5,
                                       offset_v=0.0)
        line = spec.to_spice_line()
        self.assertIn("SIN(", line)
        self.assertIn("1000", line)

    def test_square_spice_line(self):
        spec = function_generator_spec("square", freq_hz=500.0, amplitude_v=2.5,
                                       duty_cycle=0.5)
        line = spec.to_spice_line()
        self.assertIn("PULSE(", line)

    def test_triangle_spice_line(self):
        spec = function_generator_spec("triangle", freq_hz=200.0, amplitude_v=1.0)
        line = spec.to_spice_line()
        self.assertIn("PULSE(", line)

    def test_tran_directive_covers_n_cycles(self):
        spec = function_generator_spec("sine", freq_hz=1000.0, amplitude_v=1.0)
        tran = spec.to_tran_directive(n_cycles=5.0)
        self.assertIn(".TRAN", tran)

    def test_invalid_waveform_raises(self):
        with self.assertRaises(ValueError):
            function_generator_spec("sawtooth", freq_hz=1000.0, amplitude_v=1.0)

    def test_invalid_freq_raises(self):
        with self.assertRaises(ValueError):
            function_generator_spec("sine", freq_hz=-1.0, amplitude_v=1.0)

    def test_invalid_duty_raises(self):
        with self.assertRaises(ValueError):
            function_generator_spec("square", freq_hz=1000.0, amplitude_v=1.0,
                                    duty_cycle=1.5)

    def test_source_name_appears_in_line(self):
        spec = function_generator_spec("sine", freq_hz=1000.0, amplitude_v=1.0,
                                       source_name="gen")
        self.assertIn("Vgen", spec.to_spice_line())


# ---------------------------------------------------------------------------
# Probe tests
# ---------------------------------------------------------------------------

class TestProbeNodes(unittest.TestCase):

    def _dc_waveforms(self):
        """Two-node DC op-point result: V(vdd)=5V, V(out)=2.5V."""
        t = [0.0]
        return [
            _list_waveform("V(vdd)", t, [5.0]),
            _list_waveform("V(out)", t, [2.5]),
        ]

    def test_dc_node_voltage(self):
        wf = self._dc_waveforms()
        result = probe_nodes(wf, ["V(out)"])
        self.assertEqual(len(result.probes), 1)
        p = result.probes[0]
        self.assertFalse(p.not_found)
        self.assertAlmostEqual(p.dc_mean, 2.5, delta=1e-9)
        self.assertEqual(p.unit, "V")

    def test_multi_node_dc(self):
        wf = self._dc_waveforms()
        result = probe_nodes(wf, ["V(vdd)", "V(out)"])
        self.assertEqual(len(result.probes), 2)
        vals = {p.node: p.dc_mean for p in result.probes}
        self.assertAlmostEqual(vals["V(vdd)"], 5.0, delta=1e-9)
        self.assertAlmostEqual(vals["V(out)"], 2.5, delta=1e-9)

    def test_missing_node_flagged(self):
        wf = self._dc_waveforms()
        result = probe_nodes(wf, ["V(missing)"])
        self.assertTrue(result.probes[0].not_found)
        self.assertTrue(any("missing" in w for w in result.warnings))

    def test_at_time_nearest_sample(self):
        """at_time= returns the sample nearest the requested time."""
        t = [0.0, 1e-6, 2e-6, 3e-6]
        y = [0.0, 1.0, 2.0, 3.0]
        wf = [_list_waveform("V(n)", t, y)]
        result = probe_nodes(wf, ["V(n)"], at_time=2.1e-6)
        p = result.probes[0]
        # Nearest to 2.1e-6 is index 2 → value 2.0
        self.assertAlmostEqual(p.value_v_or_a, 2.0, delta=0.01)

    def test_overlay_format_label(self):
        wf = self._dc_waveforms()
        result = probe_nodes(wf, ["V(out)"])
        overlay = format_probe_overlay(result.probes[0])
        self.assertIn("label", overlay)
        self.assertIn("V", overlay["label"])

    def test_overlay_format_not_found(self):
        wf = self._dc_waveforms()
        result = probe_nodes(wf, ["V(ghost)"])
        overlay = format_probe_overlay(result.probes[0])
        self.assertTrue(overlay["not_found"])


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

class TestLLMToolRegistration(unittest.IsolatedAsyncioTestCase):

    def test_eda_virtual_instrument_registered(self):
        names = {t.spec.name for t in Registry}
        self.assertIn("eda_virtual_instrument", names)

    def test_eda_probe_nodes_registered(self):
        names = {t.spec.name for t in Registry}
        self.assertIn("eda_probe_nodes", names)

    def test_eda_virtual_instrument_spec_has_instrument(self):
        tool = next(t for t in Registry if t.spec.name == "eda_virtual_instrument")
        props = tool.spec.input_schema.get("properties", {})
        self.assertIn("instrument", props)

    def test_eda_probe_nodes_spec_has_nodes(self):
        tool = next(t for t in Registry if t.spec.name == "eda_probe_nodes")
        required = tool.spec.input_schema.get("required", [])
        self.assertIn("nodes", required)


# ---------------------------------------------------------------------------
# LLM tool arg validation
# ---------------------------------------------------------------------------

class TestLLMToolArgValidation(unittest.IsolatedAsyncioTestCase):

    async def _call(self, name, payload):
        tool = next(t for t in Registry if t.spec.name == name)
        return json.loads(await tool.run(None, json.dumps(payload).encode()))

    async def test_missing_instrument_is_error(self):
        result = await self._call("eda_virtual_instrument", {})
        self.assertIn("error", result)

    async def test_invalid_instrument_is_error(self):
        result = await self._call("eda_virtual_instrument",
                                  {"instrument": "laser"})
        self.assertIn("error", result)

    async def test_oscilloscope_missing_waveforms_is_error(self):
        result = await self._call("eda_virtual_instrument", {
            "instrument": "oscilloscope",
            "channels": ["V(out)"],
        })
        self.assertIn("error", result)

    async def test_multimeter_missing_node_is_error(self):
        result = await self._call("eda_virtual_instrument", {
            "instrument": "multimeter",
            "waveforms": [{"name": "V(x)", "x": [0.0], "y": [1.0]}],
        })
        self.assertIn("error", result)

    async def test_fgen_missing_freq_is_error(self):
        result = await self._call("eda_virtual_instrument", {
            "instrument": "function_generator",
            "waveform": "sine",
            "amplitude_v": 1.0,
        })
        self.assertIn("error", result)

    async def test_probe_nodes_missing_waveforms_is_error(self):
        result = await self._call("eda_probe_nodes",
                                  {"nodes": ["V(out)"]})
        self.assertIn("error", result)

    async def test_probe_nodes_missing_nodes_is_error(self):
        result = await self._call("eda_probe_nodes",
                                  {"waveforms": []})
        self.assertIn("error", result)

    async def test_invalid_json_is_error(self):
        tool = next(t for t in Registry if t.spec.name == "eda_virtual_instrument")
        result = json.loads(await tool.run(None, b"not-json"))
        self.assertIn("error", result)

    async def test_oscilloscope_happy_path(self):
        t, y = _sine_wave(1000.0, 1.0, 0.0)
        result = await self._call("eda_virtual_instrument", {
            "instrument": "oscilloscope",
            "waveforms": [{"name": "V(out)", "x": t, "y": y,
                           "kind": "V", "xUnit": "s", "yUnit": "V"}],
            "channels": ["V(out)"],
        })
        self.assertIn("channels", result)
        ch = result["channels"][0]
        self.assertAlmostEqual(ch["vpp"], 2.0, delta=0.05)

    async def test_multimeter_dc_happy_path(self):
        t = [0.0, 1e-6]
        y = [2.5, 2.5]
        result = await self._call("eda_virtual_instrument", {
            "instrument": "multimeter",
            "waveforms": [{"name": "V(out)", "x": t, "y": y,
                           "kind": "V", "xUnit": "s", "yUnit": "V"}],
            "node": "V(out)",
            "mode": "dc_voltage",
        })
        self.assertAlmostEqual(result["value"], 2.5, delta=0.001)

    async def test_fgen_sine_happy_path(self):
        result = await self._call("eda_virtual_instrument", {
            "instrument": "function_generator",
            "waveform": "sine",
            "freq_hz": 1000.0,
            "amplitude_v": 1.5,
        })
        self.assertIn("spice_line", result)
        self.assertIn("SIN(", result["spice_line"])

    async def test_probe_nodes_happy_path(self):
        t = [0.0]
        result = await self._call("eda_probe_nodes", {
            "waveforms": [{"name": "V(out)", "x": t, "y": [3.3],
                           "kind": "V", "xUnit": "s", "yUnit": "V"}],
            "nodes": ["V(out)"],
        })
        self.assertIn("probes", result)
        self.assertEqual(len(result["probes"]), 1)
        self.assertFalse(result["probes"][0]["not_found"])


if __name__ == "__main__":
    unittest.main()
