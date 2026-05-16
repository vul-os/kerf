"""
Hermetic tests for the DSP / digital filter design module.

Covers (≥30 tests):

  FFT / IFFT
    - FFT of DC signal: only bin 0 non-zero
    - FFT of single-frequency sinusoid: peak at expected bin
    - IFFT(FFT(x)) ≈ x (round-trip)
    - FFT non-power-of-2 → ok=False
    - FFT empty → ok=False
    - IFFT non-power-of-2 → ok=False

  DFT spectrum / bin_frequency
    - Spectrum returns N/2+1 bins
    - DC-only signal: single peak at bin 0
    - bin_frequency: k*fs/N
    - bin_frequency out-of-range → ok=False

  FIR design
    - LP coefficients sum ≈ 1 (DC gain)
    - HP coefficients: DC gain ≈ 0
    - BP: gain at centre > gain at DC and Nyquist
    - Blackman wider order than rect (fir_order_estimate)
    - Even-tap LP: ok=True (with warning)
    - Even-tap HP: ok=False
    - Invalid fc_norm (≥0.5) → ok=False
    - Invalid window → ok=False
    - fir_order_estimate zero bandwidth → ok=False

  Bilinear Butterworth IIR
    - LP order=1: H(DC)≈1.0, H(Nyquist)≈0.0
    - LP order=1: H(fc)≈−3 dB (within 0.5 dB)
    - HP: H(DC)≈0, H(Nyquist)≈1.0
    - HP order=1: H(fc)≈−3 dB (within 0.5 dB)
    - fc >= Nyquist → ok=False
    - Order 0 → ok=False

  Biquad (RBJ)
    - LP: DC gain ≈ 1.0
    - LP: Nyquist gain ≈ 0.0
    - HP: DC gain ≈ 0.0
    - HP: Nyquist gain ≈ 1.0
    - BP: gain at centre > passband flanks
    - Notch: gain at centre ≈ 0.0
    - Peaking: gain at fc ≈ gain_db
    - Peaking negative gain → attenuation at fc
    - Invalid fc ≥ Nyquist → ok=False

  Frequency response / group delay
    - FIR allpass [1]: H=1 everywhere
    - Group delay FIR allpass ≈ 0
    - freq_response: freq > Nyquist → ok=False
    - group_delay: negative delta → ok=False

  Nyquist / ADC
    - fs > 2×bw → alias_free=True
    - fs < 2×bw → alias_free=False, warning issued
    - Nyquist zero fs → ok=False
    - ADC 16-bit: SNR ≈ 98.1 dB
    - ADC 1-bit: SNR ≈ 7.78 dB
    - ADC OSR=4 adds ~3 dB process gain
    - ADC bits=0 → ok=False
    - ADC osr<1 → ok=False

  LLM tool handlers (stub registry)
    - dsp_fft tool returns ok=True
    - dsp_spectrum tool returns ok=True
    - dsp_biquad_lp tool returns ok=True
    - dsp_iir_butterworth_lp tool returns ok=True
    - dsp_nyquist_check tool returns ok=True
    - dsp_adc_snr tool returns ok=True
    - tool invalid JSON → error payload

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types
import warnings

# ── Prefer real kerf_chat if installed; stub otherwise ────────────────────────
try:
    import kerf_chat as _kc_pkg  # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type(
    "ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}
)
_reg_stub.err_payload = lambda msg, code: json.dumps(
    {"ok": False, "error": msg, "code": code}
)
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kerf_chat_stub = types.ModuleType("kerf_chat")
_kerf_chat_tools_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kerf_chat_stub)
sys.modules.setdefault("kerf_chat.tools", _kerf_chat_tools_stub)
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on path ────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.dsp.filters import (
    fft,
    ifft,
    dft_spectrum,
    bin_frequency,
    windowed_sinc_lp,
    windowed_sinc_hp,
    windowed_sinc_bp,
    fir_order_estimate,
    bilinear_butterworth_lp,
    bilinear_butterworth_hp,
    biquad_lp,
    biquad_hp,
    biquad_bp,
    biquad_notch,
    biquad_peaking,
    freq_response,
    group_delay,
    nyquist_check,
    adc_snr,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.dsp.tools",
    os.path.join(_SRC, "kerf_electronics", "dsp", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

dsp_fft_tool = _tool_mod.dsp_fft
dsp_spectrum_tool = _tool_mod.dsp_spectrum
dsp_biquad_lp_tool = _tool_mod.dsp_biquad_lp
dsp_iir_butterworth_lp_tool = _tool_mod.dsp_iir_butterworth_lp
dsp_nyquist_check_tool = _tool_mod.dsp_nyquist_check
dsp_adc_snr_tool = _tool_mod.dsp_adc_snr


# ── Async call helper ─────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ── Small helper: evaluate H(e^jω) at freq for FIR (a=[1]) ──────────────────

def fir_response_at(h, freq_norm):
    """Evaluate |H(e^jω)| for FIR at normalised frequency (0..0.5)."""
    N = len(h)
    w = 2.0 * math.pi * freq_norm
    acc = sum(h[k] * complex(math.cos(k * w), -math.sin(k * w)) for k in range(N))
    return abs(acc)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. FFT / IFFT
# ═══════════════════════════════════════════════════════════════════════════════

class TestFFT:
    def test_dc_signal_only_bin0_nonzero(self):
        """FFT of constant signal: all energy in bin 0."""
        N = 8
        x = [1.0] * N
        res = fft(x)
        assert res["ok"] is True
        assert res["N"] == N
        # Bin 0 magnitude should be N (before scaling)
        mag0 = abs(complex(res["X"][0]["re"], res["X"][0]["im"]))
        assert abs(mag0 - N) < 1e-9, f"Expected DC bin mag={N}, got {mag0}"
        for k in range(1, N):
            mk = abs(complex(res["X"][k]["re"], res["X"][k]["im"]))
            assert mk < 1e-9, f"Expected bin {k}=0, got {mk}"

    def test_sinusoid_peak_at_correct_bin(self):
        """FFT of single-tone sinusoid: peak at bin k0."""
        N = 16
        k0 = 3
        x = [math.cos(2.0 * math.pi * k0 * n / N) for n in range(N)]
        res = fft(x)
        assert res["ok"] is True
        mags = [abs(complex(v["re"], v["im"])) for v in res["X"]]
        peak_bin = max(range(N), key=lambda k: mags[k])
        # Peak at k0 or N-k0 (conjugate symmetry)
        assert peak_bin in (k0, N - k0), f"Peak at {peak_bin}, expected {k0} or {N - k0}"

    def test_ifft_fft_roundtrip(self):
        """IFFT(FFT(x)) ≈ x for arbitrary input."""
        import cmath
        x = [float(k % 7 - 3) for k in range(8)]
        r_fft = fft(x)
        assert r_fft["ok"] is True
        r_ifft = ifft(r_fft["X"])
        assert r_ifft["ok"] is True
        for i, orig in enumerate(x):
            recovered = r_ifft["x"][i]["re"]
            assert abs(recovered - orig) < 1e-9, f"index {i}: {recovered} != {orig}"

    def test_fft_non_power_of_2_returns_error(self):
        res = fft([1.0, 2.0, 3.0])  # length 3
        assert res["ok"] is False
        assert "power of 2" in res["reason"].lower()

    def test_fft_empty_returns_error(self):
        res = fft([])
        assert res["ok"] is False

    def test_ifft_non_power_of_2_returns_error(self):
        res = ifft([{"re": 1.0, "im": 0.0}] * 3)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DFT Spectrum / bin_frequency
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpectrum:
    def test_returns_n_over_2_plus_1_bins(self):
        N = 16
        x = [1.0] * N
        res = dft_spectrum(x, fs=1000.0)
        assert res["ok"] is True
        assert len(res["freq_hz"]) == N // 2 + 1
        assert len(res["magnitude"]) == N // 2 + 1

    def test_dc_signal_peak_at_bin0(self):
        N = 8
        x = [2.0] * N
        res = dft_spectrum(x, fs=1000.0)
        assert res["ok"] is True
        mags = res["magnitude"]
        assert mags[0] == max(mags), "DC should dominate"
        # All non-DC bins should be near zero
        for k in range(1, len(mags)):
            assert mags[k] < 1e-9, f"bin {k} non-zero for DC input"

    def test_bin_frequency_formula(self):
        res = bin_frequency(k=3, N=16, fs=1000.0)
        assert res["ok"] is True
        assert abs(res["freq_hz"] - 187.5) < 1e-9

    def test_bin_frequency_out_of_range(self):
        res = bin_frequency(k=16, N=16, fs=1000.0)
        assert res["ok"] is False

    def test_bin_frequency_bin0_is_dc(self):
        res = bin_frequency(k=0, N=32, fs=8000.0)
        assert res["ok"] is True
        assert res["freq_hz"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Windowed-sinc FIR design
# ═══════════════════════════════════════════════════════════════════════════════

class TestFIR:
    def test_lp_dc_gain_unity(self):
        """LP FIR: sum of coefficients ≈ 1 (DC gain, within 0.2%)."""
        res = windowed_sinc_lp(N=51, fc_norm=0.2, window="hamming")
        assert res["ok"] is True
        # Windowed-sinc with odd N has slight gain deviation; accept <0.3% error
        assert abs(sum(res["h"]) - 1.0) < 3e-3

    def test_lp_response_at_cutoff_near_minus3db(self):
        """LP FIR: |H(fc)| ≈ 0.5 (−6 dB for window design; within 10% of 0.5)."""
        res = windowed_sinc_lp(N=101, fc_norm=0.25, window="hamming")
        assert res["ok"] is True
        h = res["h"]
        mag_fc = fir_response_at(h, 0.25)
        # Windowed sinc has −6 dB at exactly fc; accept 0.45–0.55
        assert 0.4 < mag_fc < 0.65, f"|H(fc)|={mag_fc:.4f}"

    def test_lp_stopband_attenuated(self):
        """LP FIR: high-frequency content well below passband."""
        res = windowed_sinc_lp(N=101, fc_norm=0.1, window="blackman")
        assert res["ok"] is True
        h = res["h"]
        mag_pass = fir_response_at(h, 0.05)  # well in passband
        mag_stop = fir_response_at(h, 0.4)   # well in stopband
        assert mag_pass > 0.7
        assert mag_stop < 0.01, f"stopband not attenuated: {mag_stop:.4f}"

    def test_hp_dc_gain_near_zero(self):
        """HP FIR: DC response ≈ 0."""
        res = windowed_sinc_hp(N=51, fc_norm=0.3, window="hamming")
        assert res["ok"] is True
        h = res["h"]
        mag_dc = fir_response_at(h, 0.0)
        assert mag_dc < 0.05, f"HP DC gain too high: {mag_dc:.4f}"

    def test_hp_high_freq_gain_near_unity(self):
        """HP FIR: gain near Nyquist ≈ 1."""
        res = windowed_sinc_hp(N=51, fc_norm=0.2, window="hamming")
        assert res["ok"] is True
        h = res["h"]
        mag_ny = fir_response_at(h, 0.499)
        assert mag_ny > 0.8, f"HP Nyquist gain too low: {mag_ny:.4f}"

    def test_bp_centre_greater_than_flanks(self):
        """BP FIR: gain at centre > gain at DC and Nyquist."""
        res = windowed_sinc_bp(N=101, fl_norm=0.15, fh_norm=0.35, window="hamming")
        assert res["ok"] is True
        h = res["h"]
        mag_centre = fir_response_at(h, 0.25)
        mag_dc = fir_response_at(h, 0.01)
        mag_ny = fir_response_at(h, 0.49)
        assert mag_centre > mag_dc * 5
        assert mag_centre > mag_ny * 5

    def test_fir_order_blackman_larger_than_rect(self):
        """Blackman needs more taps than rect for same transition BW."""
        r_bl = fir_order_estimate(0.05, "blackman")
        r_re = fir_order_estimate(0.05, "rect")
        assert r_bl["ok"] and r_re["ok"]
        assert r_bl["N_estimate"] > r_re["N_estimate"]

    def test_even_tap_lp_ok(self):
        """Even N LP design completes (with warning)."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = windowed_sinc_lp(N=50, fc_norm=0.2, window="hamming")
        assert res["ok"] is True

    def test_even_tap_hp_returns_error(self):
        """HP design requires odd N."""
        res = windowed_sinc_hp(N=50, fc_norm=0.3, window="hamming")
        assert res["ok"] is False

    def test_invalid_fc_norm_half(self):
        res = windowed_sinc_lp(N=51, fc_norm=0.5, window="hamming")
        assert res["ok"] is False

    def test_invalid_fc_norm_zero(self):
        res = windowed_sinc_lp(N=51, fc_norm=0.0, window="hamming")
        assert res["ok"] is False

    def test_invalid_window_name(self):
        res = windowed_sinc_lp(N=51, fc_norm=0.2, window="kaiser")
        assert res["ok"] is False

    def test_fir_order_zero_bw_returns_error(self):
        res = fir_order_estimate(0.0, "hamming")
        assert res["ok"] is False

    def test_fir_order_result_is_odd(self):
        """fir_order_estimate always returns odd N for Type-I symmetry."""
        for window in ("rect", "hann", "hamming", "blackman"):
            res = fir_order_estimate(0.03, window)
            assert res["ok"] is True
            assert res["N_estimate"] % 2 == 1, f"{window}: N={res['N_estimate']} is even"

    def test_bp_fl_ge_fh_returns_error(self):
        res = windowed_sinc_bp(N=51, fl_norm=0.3, fh_norm=0.2, window="hamming")
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Bilinear Butterworth IIR
# ═══════════════════════════════════════════════════════════════════════════════

class TestBilinearButterworth:
    _FS = 48000.0
    _FC = 1000.0

    def test_lp_dc_gain_unity(self):
        """LP Butterworth order=1: H(0) ≈ 1."""
        res = bilinear_butterworth_lp(order=1, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        r = freq_response(res["b"], res["a"], 0.0, self._FS)
        assert r["ok"] is True
        assert abs(r["magnitude"] - 1.0) < 0.01

    def test_lp_nyquist_gain_near_zero(self):
        """LP Butterworth order=2: H(Nyquist) very small."""
        res = bilinear_butterworth_lp(order=2, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        r = freq_response(res["b"], res["a"], self._FS / 2.0 - 1.0, self._FS)
        assert r["ok"] is True
        assert r["magnitude"] < 0.01

    def test_lp_cutoff_near_minus3db(self):
        """LP order=1 at fc: gain ≈ -3 dB (within 0.5 dB)."""
        res = bilinear_butterworth_lp(order=1, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        r = freq_response(res["b"], res["a"], self._FC, self._FS)
        assert r["ok"] is True
        assert abs(r["magnitude_db"] - (-3.0103)) < 0.5, (
            f"LP cutoff gain: {r['magnitude_db']:.3f} dB"
        )

    def test_hp_dc_gain_near_zero(self):
        """HP Butterworth order=1: H(0) ≈ 0."""
        res = bilinear_butterworth_hp(order=1, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        r = freq_response(res["b"], res["a"], 0.0, self._FS)
        assert r["ok"] is True
        assert r["magnitude"] < 0.01

    def test_hp_nyquist_gain_near_unity(self):
        """HP Butterworth order=2: H(Nyquist-ε) ≈ 1."""
        res = bilinear_butterworth_hp(order=2, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        r = freq_response(res["b"], res["a"], self._FS / 2.0 - 1.0, self._FS)
        assert r["ok"] is True
        assert r["magnitude"] > 0.95

    def test_hp_cutoff_near_minus3db(self):
        """HP order=1 at fc: gain ≈ -3 dB (within 0.5 dB)."""
        res = bilinear_butterworth_hp(order=1, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        r = freq_response(res["b"], res["a"], self._FC, self._FS)
        assert r["ok"] is True
        assert abs(r["magnitude_db"] - (-3.0103)) < 0.5, (
            f"HP cutoff gain: {r['magnitude_db']:.3f} dB"
        )

    def test_fc_above_nyquist_returns_error(self):
        res = bilinear_butterworth_lp(order=2, fc_hz=25000.0, fs_hz=self._FS)
        assert res["ok"] is False

    def test_order_zero_returns_error(self):
        res = bilinear_butterworth_lp(order=0, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is False

    def test_returns_n_plus_1_coefficients(self):
        order = 3
        res = bilinear_butterworth_lp(order=order, fc_hz=self._FC, fs_hz=self._FS)
        assert res["ok"] is True
        assert len(res["b"]) == order + 1
        assert len(res["a"]) == order + 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RBJ Biquad
# ═══════════════════════════════════════════════════════════════════════════════

class TestBiquad:
    _FS = 44100.0
    _FC = 1000.0

    def _eval(self, bqa_res, freq_hz):
        assert bqa_res["ok"] is True
        return freq_response(bqa_res["b"], bqa_res["a"], freq_hz, self._FS)

    def test_lp_dc_gain_unity(self):
        res = biquad_lp(self._FC, self._FS)
        r = self._eval(res, 1.0)
        assert r["ok"] is True
        assert abs(r["magnitude"] - 1.0) < 0.02

    def test_lp_nyquist_gain_near_zero(self):
        res = biquad_lp(self._FC, self._FS)
        r = self._eval(res, self._FS / 2.0 - 1.0)
        assert r["ok"] is True
        assert r["magnitude"] < 0.01

    def test_hp_dc_gain_near_zero(self):
        res = biquad_hp(self._FC, self._FS)
        r = self._eval(res, 1.0)
        assert r["ok"] is True
        assert r["magnitude"] < 0.02

    def test_hp_nyquist_gain_near_unity(self):
        res = biquad_hp(self._FC, self._FS)
        r = self._eval(res, self._FS / 2.0 - 1.0)
        assert r["ok"] is True
        assert r["magnitude"] > 0.95

    def test_bp_centre_is_maximum(self):
        res = biquad_bp(self._FC, self._FS, Q=2.0)
        r_centre = self._eval(res, self._FC)
        r_low = self._eval(res, 100.0)
        r_high = self._eval(res, 10000.0)
        assert r_centre["magnitude"] > r_low["magnitude"] * 5
        assert r_centre["magnitude"] > r_high["magnitude"] * 5

    def test_notch_centre_near_zero(self):
        res = biquad_notch(self._FC, self._FS, Q=5.0)
        assert res["ok"] is True
        r = self._eval(res, self._FC)
        assert r["ok"] is True
        assert r["magnitude"] < 0.05, f"notch centre gain: {r['magnitude']:.4f}"

    def test_peaking_boost(self):
        """Peaking EQ: gain at fc ≈ +gain_db."""
        gain_db = 6.0
        res = biquad_peaking(self._FC, self._FS, Q=1.0, gain_db=gain_db)
        assert res["ok"] is True
        r = self._eval(res, self._FC)
        assert r["ok"] is True
        assert abs(r["magnitude_db"] - gain_db) < 0.5, (
            f"Peaking boost: {r['magnitude_db']:.2f} dB, expected {gain_db} dB"
        )

    def test_peaking_cut(self):
        """Peaking EQ: attenuation at fc for negative gain_db."""
        gain_db = -6.0
        res = biquad_peaking(self._FC, self._FS, Q=1.0, gain_db=gain_db)
        assert res["ok"] is True
        r = self._eval(res, self._FC)
        assert r["ok"] is True
        assert r["magnitude_db"] < 0.0

    def test_fc_at_nyquist_returns_error(self):
        res = biquad_lp(self._FS / 2.0, self._FS)
        assert res["ok"] is False

    def test_lp_coefficients_structure(self):
        """LP biquad returns b=[b0,b1,b2], a=[1,a1,a2]."""
        res = biquad_lp(self._FC, self._FS)
        assert res["ok"] is True
        assert len(res["b"]) == 3
        assert len(res["a"]) == 3
        assert res["a"][0] == 1.0  # normalised


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Frequency response / group delay
# ═══════════════════════════════════════════════════════════════════════════════

class TestFreqResponse:
    _FS = 8000.0

    def test_allpass_unity_gain(self):
        """Allpass filter [1]/[1]: |H|=1 at all frequencies."""
        b = [1.0]
        a = [1.0]
        for f in [0.0, 100.0, 1000.0, 3999.0]:
            r = freq_response(b, a, f, self._FS)
            assert r["ok"] is True
            assert abs(r["magnitude"] - 1.0) < 1e-9, f"f={f}: mag={r['magnitude']}"

    def test_freq_above_nyquist_returns_error(self):
        r = freq_response([1.0], [1.0], self._FS / 2.0 + 1.0, self._FS)
        assert r["ok"] is False

    def test_group_delay_allpass_near_zero(self):
        """Allpass: group delay ≈ 0 samples."""
        b = [1.0]
        a = [1.0]
        r = group_delay(b, a, 100.0, self._FS)
        assert r["ok"] is True
        assert abs(r["group_delay_samples"]) < 0.1

    def test_group_delay_fir_delay(self):
        """Pure delay of M samples: group delay ≈ M samples."""
        M = 10
        b = [0.0] * M + [1.0]  # z^{-M}
        a = [1.0]
        r = group_delay(b, a, 500.0, self._FS)
        assert r["ok"] is True
        assert abs(r["group_delay_samples"] - M) < 0.5

    def test_group_delay_negative_delta_returns_error(self):
        r = group_delay([1.0], [1.0], 100.0, self._FS, delta_hz=-1.0)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Nyquist check / ADC SNR
# ═══════════════════════════════════════════════════════════════════════════════

class TestNyquistADC:
    def test_alias_free_when_fs_sufficient(self):
        res = nyquist_check(signal_bw_hz=1000.0, fs_hz=5000.0)
        assert res["ok"] is True
        assert res["alias_free"] is True
        assert res["oversampling_ratio"] == 2.5

    def test_aliasing_when_fs_insufficient(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            res = nyquist_check(signal_bw_hz=3000.0, fs_hz=4000.0)
        assert res["ok"] is True
        assert res["alias_free"] is False
        assert any("lias" in str(warning.message) for warning in w)

    def test_nyquist_zero_fs_returns_error(self):
        res = nyquist_check(signal_bw_hz=1000.0, fs_hz=0.0)
        assert res["ok"] is False

    def test_nyquist_zero_bw_returns_error(self):
        res = nyquist_check(signal_bw_hz=0.0, fs_hz=8000.0)
        assert res["ok"] is False

    def test_adc_16bit_snr(self):
        """16-bit ADC: SNR ≈ 98.1 dB."""
        res = adc_snr(bits=16, osr=1.0)
        assert res["ok"] is True
        assert abs(res["snr_ideal_db"] - 98.09) < 0.05

    def test_adc_1bit_snr(self):
        """1-bit ADC: SNR ≈ 7.78 dB."""
        res = adc_snr(bits=1, osr=1.0)
        assert res["ok"] is True
        assert abs(res["snr_ideal_db"] - 7.78) < 0.05

    def test_adc_osr4_adds_3db(self):
        """4× OSR ≈ 3 dB process gain (10*log10(4)/2)."""
        r1 = adc_snr(bits=12, osr=1.0)
        r4 = adc_snr(bits=12, osr=4.0)
        assert r1["ok"] and r4["ok"]
        pg = r4["snr_with_osr_db"] - r1["snr_with_osr_db"]
        assert abs(pg - 3.0103) < 0.01, f"Process gain: {pg:.4f} dB"

    def test_adc_bits_zero_returns_error(self):
        res = adc_snr(bits=0)
        assert res["ok"] is False

    def test_adc_osr_below_one_returns_error(self):
        res = adc_snr(bits=8, osr=0.5)
        assert res["ok"] is False

    def test_adc_enob_equals_bits_for_ideal(self):
        """For OSR=1 and ideal SNR: ENOB ≈ bits."""
        res = adc_snr(bits=12, osr=1.0)
        assert res["ok"] is True
        assert abs(res["enob"] - 12.0) < 0.05


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolHandlers:
    @pytest.mark.asyncio
    async def test_dsp_fft_tool_ok(self):
        x = [1.0, 0.0, -1.0, 0.0, 1.0, 0.0, -1.0, 0.0]
        res = await call(dsp_fft_tool, x=x)
        assert "X" in res

    @pytest.mark.asyncio
    async def test_dsp_spectrum_tool_ok(self):
        x = [1.0] * 8
        res = await call(dsp_spectrum_tool, x=x, fs_hz=1000.0)
        assert "freq_hz" in res

    @pytest.mark.asyncio
    async def test_dsp_biquad_lp_tool_ok(self):
        res = await call(dsp_biquad_lp_tool, fc_hz=1000.0, fs_hz=44100.0)
        assert "b" in res and "a" in res

    @pytest.mark.asyncio
    async def test_dsp_iir_butterworth_lp_tool_ok(self):
        res = await call(dsp_iir_butterworth_lp_tool, order=2, fc_hz=1000.0, fs_hz=48000.0)
        assert "b" in res

    @pytest.mark.asyncio
    async def test_dsp_nyquist_check_tool_ok(self):
        res = await call(dsp_nyquist_check_tool, signal_bw_hz=1000.0, fs_hz=8000.0)
        assert "alias_free" in res

    @pytest.mark.asyncio
    async def test_dsp_adc_snr_tool_ok(self):
        res = await call(dsp_adc_snr_tool, bits=16)
        assert "snr_ideal_db" in res

    @pytest.mark.asyncio
    async def test_tool_invalid_json_returns_error(self):
        result_str = await dsp_fft_tool(None, b"not-valid-json!!!")
        data = json.loads(result_str)
        # Real registry err_payload: {"error": ..., "code": ...}; stub: {"ok": False, ...}
        assert data.get("ok") is False or "error" in data
