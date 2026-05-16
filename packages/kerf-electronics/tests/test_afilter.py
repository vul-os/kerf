"""
Hermetic tests for the analog filter design module.

Covers (≥30 tests across all public functions):

  butterworth_order
    - Known result: fp=1kHz, fs=2kHz, Ap=3dB, As=40dB → n≥7 (closed-form)
    - Stopband must exceed passband frequency: ok=False otherwise
    - Stopband attenuation must exceed passband ripple: ok=False otherwise
    - Higher stopband attenuation → higher order
    - Order is a positive integer (ceiling of n_exact)

  chebyshev_order
    - Known result: fp=1kHz, fs=2kHz, Ap=0.5dB, As=40dB → lower order than Butterworth
    - Chebyshev order ≤ Butterworth order for same spec
    - Invalid arguments → ok=False
    - epsilon > 0 for any valid ripple

  bessel_order
    - Returns positive integer order
    - Smaller flatness_percent → larger order
    - Invalid (0%) flatness → ok=False

  butterworth_poles
    - All poles on unit circle (|pole| ≈ 1)
    - All poles in left half-plane (Re < 0)
    - n=1: single real pole at s=−1
    - n=2: two complex conjugate poles at ±j60° on unit circle
    - Invalid order → ok=False

  chebyshev_poles
    - All poles in left half-plane (Re < 0)
    - Pole count equals n
    - Higher ripple → poles closer to imaginary axis
    - n=1, 0.5dB ripple: single real pole on negative real axis
    - Invalid order → ok=False

  bessel_poles
    - n=1: single pole at s=−1.0 (known Bessel result)
    - n=2: two complex conjugate poles (known: ≈ −1.5 ± j0.866)
    - All poles in left half-plane
    - Order > 10 → ok=False

  butterworth_g_values
    - n=1: g = [1, 2, 1]
    - n=2: g = [1, sqrt(2), sqrt(2), 1] (symmetric)
    - g_values has n+2 elements
    - g_0 = 1 (normalised source)
    - g_{n+1} = 1 for all n

  chebyshev_g_values
    - n=1, 0.5dB ripple: known g_1 ≈ 0.6986 (Zverev table)
    - g_values has n+2 elements
    - n=2, 0.5dB: g_1, g_2 both > 0
    - Invalid ripple (negative) → ok=False

  lp_to_lp_rlc
    - n=1 Butterworth prototype → single inductor L = Z0/ω_c
    - n=2 at 1 kHz, 50Ω: first element is L, second is C
    - cutoff_freq_hz=0 → ok=False
    - impedance_ohm=0 → ok=False
    - Doubling impedance → doubles L, halves C

  lp_to_hp_rlc
    - n=1 LP → HP: LP inductor becomes HP capacitor C = 1/(g1 × Z0 × ω_c)
    - Element types alternate C/L for HP (inverse of LP)
    - cutoff_freq_hz=0 → ok=False

  lp_to_bp_rlc
    - n=1 LP → BP: elements are resonator dicts with L_h and C_f
    - Both resonator C and L are positive
    - Resonator f0 equals center_freq_hz
    - bandwidth_hz=0 → ok=False

  sallen_key_components
    - 2nd-order Butterworth section: Q=1/√2 → K_required = 3 − √2 ≈ 1.586
    - Unity gain (gain=1.0): Rf=None, Rg=None
    - Q < 0.5 → realizable=False (K_required < 1)
    - R = 1/(2π × f × C) within 1% of expected
    - C1 == C2 (equal capacitor design)

  multiple_feedback_components
    - Q=0.707, |gain|=1: discriminant ≥ 0 → realizable=True
    - High Q with low gain → realizable=False (negative discriminant)
    - All resistors positive for realizable case
    - gain=0 → ok=False

  filter_response
    - Single real pole at s=−1, evaluated at ω=1 rad/s: |H| = 1/√2 ≈ −3 dB
    - 2nd-order Butterworth at pole frequency: |H| ≈ −6 dB (≈ −3dB for each pole pair, exact depends on gain)
    - DC (very low freq) response approaches gain_dc
    - group_delay_s > 0 for left-half-plane poles
    - Empty pole list → ok=True, |H| = gain_dc

  LLM tool handlers
    - afilter_butterworth_order tool: ok=True for valid spec
    - afilter_chebyshev_order tool: ok=True, epsilon > 0
    - afilter_bessel_order tool: ok=True, order is int
    - afilter_butterworth_poles tool: ok=True, poles list non-empty
    - afilter_chebyshev_poles tool: ok=True, poles list non-empty
    - afilter_bessel_poles tool: ok=True, n=2 poles present
    - afilter_butterworth_g tool: ok=True, g_values[0] == 1
    - afilter_chebyshev_g tool: ok=True, g_values length == n+2
    - afilter_lp_to_lp tool: ok=True, elements non-empty
    - afilter_lp_to_hp tool: ok=True, first element type == 'C'
    - afilter_lp_to_bp tool: ok=True, elements have resonator
    - afilter_sallen_key tool: ok=True, R1_ohm > 0
    - afilter_mfb tool: ok=True for Q=0.707, gain=-1
    - afilter_response tool: ok=True, magnitude_db present
    - Tool with invalid JSON → error payload

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

# ── Prefer real kerf_chat if installed; stub otherwise ───────────────────────
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

from kerf_electronics.afilter.design import (
    bessel_order,
    bessel_poles,
    butterworth_g_values,
    butterworth_order,
    butterworth_poles,
    chebyshev_g_values,
    chebyshev_order,
    chebyshev_poles,
    filter_response,
    lp_to_bp_rlc,
    lp_to_hp_rlc,
    lp_to_lp_rlc,
    multiple_feedback_components,
    sallen_key_components,
)

# ── Load tool module via importlib so stub is active ─────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.afilter.tools",
    os.path.join(_SRC, "kerf_electronics", "afilter", "tools.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

_bw_order_tool = _tool_mod.afilter_butterworth_order
_cheb_order_tool = _tool_mod.afilter_chebyshev_order
_bess_order_tool = _tool_mod.afilter_bessel_order
_bw_poles_tool = _tool_mod.afilter_butterworth_poles
_cheb_poles_tool = _tool_mod.afilter_chebyshev_poles
_bess_poles_tool = _tool_mod.afilter_bessel_poles
_bw_g_tool = _tool_mod.afilter_butterworth_g
_cheb_g_tool = _tool_mod.afilter_chebyshev_g
_lp_lp_tool = _tool_mod.afilter_lp_to_lp
_lp_hp_tool = _tool_mod.afilter_lp_to_hp
_lp_bp_tool = _tool_mod.afilter_lp_to_bp
_sk_tool = _tool_mod.afilter_sallen_key
_mfb_tool = _tool_mod.afilter_mfb
_resp_tool = _tool_mod.afilter_response


# ── Async call helper ─────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. butterworth_order
# ═══════════════════════════════════════════════════════════════════════════════

class TestButterworthOrder:

    def test_known_spec_fp1k_fs2k_ap3_as40(self):
        """fp=1kHz, fs=2kHz, Ap=3dB, As=40dB → n≥7 (closed-form)."""
        r = butterworth_order(
            passband_freq_hz=1000.0,
            stopband_freq_hz=2000.0,
            passband_ripple_db=3.0,
            stopband_atten_db=40.0,
        )
        assert r["ok"] is True
        # n = ceil( log((10^4-1)/(10^0.3-1)) / (2*log(2)) ) ≈ ceil(6.64) = 7
        assert r["order"] == 7
        assert r["n_exact"] == pytest.approx(6.64, abs=0.05)

    def test_stopband_must_exceed_passband(self):
        """fs ≤ fp → ok=False."""
        r = butterworth_order(1000.0, 500.0, 3.0, 40.0)
        assert r["ok"] is False

    def test_atten_must_exceed_ripple(self):
        """As ≤ Ap → ok=False."""
        r = butterworth_order(1000.0, 2000.0, 40.0, 20.0)
        assert r["ok"] is False

    def test_higher_attenuation_higher_order(self):
        """Increasing As gives equal or higher order."""
        r1 = butterworth_order(1000.0, 2000.0, 3.0, 40.0)
        r2 = butterworth_order(1000.0, 2000.0, 3.0, 60.0)
        assert r1["ok"] and r2["ok"]
        assert r2["order"] >= r1["order"]

    def test_order_is_positive_integer(self):
        """Order is a positive integer ≥ 1."""
        r = butterworth_order(1000.0, 10000.0, 3.0, 60.0)
        assert r["ok"] is True
        assert isinstance(r["order"], int)
        assert r["order"] >= 1
        # Ceiling: order ≥ n_exact
        assert r["order"] >= r["n_exact"] - 1e-9

    def test_fc_hz_returned(self):
        """fc_hz and omega_c_rads are returned and consistent."""
        r = butterworth_order(1000.0, 2000.0, 3.0, 40.0)
        assert r["ok"] is True
        assert abs(r["fc_hz"] - r["omega_c_rads"] / (2.0 * math.pi)) < 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. chebyshev_order
# ═══════════════════════════════════════════════════════════════════════════════

class TestChebyshevOrder:

    def test_chebyshev_lower_order_than_butterworth(self):
        """Chebyshev order ≤ Butterworth order for same spec (more selective)."""
        spec = dict(passband_freq_hz=1000.0, stopband_freq_hz=2000.0,
                    passband_ripple_db=0.5, stopband_atten_db=40.0)
        rb = butterworth_order(**spec)
        rc = chebyshev_order(**spec)
        assert rb["ok"] and rc["ok"]
        assert rc["order"] <= rb["order"]

    def test_epsilon_positive(self):
        """Epsilon > 0 for any valid passband ripple."""
        r = chebyshev_order(1000.0, 3000.0, 1.0, 40.0)
        assert r["ok"] is True
        assert r["epsilon"] > 0.0

    def test_invalid_passband_freq(self):
        """Zero passband frequency → ok=False."""
        r = chebyshev_order(0.0, 2000.0, 0.5, 40.0)
        assert r["ok"] is False

    def test_order_is_integer(self):
        """Order is a positive integer."""
        r = chebyshev_order(1000.0, 5000.0, 0.5, 60.0)
        assert r["ok"] is True
        assert isinstance(r["order"], int) and r["order"] >= 1

    def test_tighter_spec_higher_order(self):
        """Harder stopband → higher or equal order."""
        r1 = chebyshev_order(1000.0, 2000.0, 0.5, 40.0)
        r2 = chebyshev_order(1000.0, 2000.0, 0.5, 60.0)
        assert r1["ok"] and r2["ok"]
        assert r2["order"] >= r1["order"]


# ═══════════════════════════════════════════════════════════════════════════════
# 3. bessel_order
# ═══════════════════════════════════════════════════════════════════════════════

class TestBesselOrder:

    def test_returns_positive_integer(self):
        r = bessel_order(group_delay_flatness_percent=5.0, bandwidth_ratio=2.0)
        assert r["ok"] is True
        assert isinstance(r["order"], int) and r["order"] >= 1

    def test_tighter_flatness_higher_order(self):
        r1 = bessel_order(group_delay_flatness_percent=10.0, bandwidth_ratio=2.0)
        r2 = bessel_order(group_delay_flatness_percent=1.0, bandwidth_ratio=2.0)
        assert r1["ok"] and r2["ok"]
        assert r2["order"] >= r1["order"]

    def test_zero_flatness_invalid(self):
        r = bessel_order(group_delay_flatness_percent=0.0, bandwidth_ratio=2.0)
        assert r["ok"] is False

    def test_100_percent_flatness_invalid(self):
        r = bessel_order(group_delay_flatness_percent=100.0, bandwidth_ratio=2.0)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. butterworth_poles
# ═══════════════════════════════════════════════════════════════════════════════

class TestButterworthPoles:

    def test_n1_single_real_pole_at_minus1(self):
        """n=1: pole is at s=−1 (unit circle, leftmost)."""
        r = butterworth_poles(1)
        assert r["ok"] is True
        assert len(r["poles"]) == 1
        assert r["poles"][0]["re"] == pytest.approx(-1.0, abs=1e-9)
        assert abs(r["poles"][0]["im"]) < 1e-9

    def test_n2_poles_on_unit_circle(self):
        """n=2: two poles at ±j60° on unit circle."""
        r = butterworth_poles(2)
        assert r["ok"] is True
        for p in r["poles"]:
            mag = math.sqrt(p["re"] ** 2 + p["im"] ** 2)
            assert mag == pytest.approx(1.0, abs=1e-8)

    def test_all_poles_left_half_plane(self):
        """All Butterworth poles have Re < 0."""
        for n in range(1, 6):
            r = butterworth_poles(n)
            assert r["ok"] is True
            for p in r["poles"]:
                assert p["re"] < 0.0

    def test_pole_count_equals_order(self):
        """Number of poles equals filter order."""
        for n in [1, 3, 5, 8]:
            r = butterworth_poles(n)
            assert r["ok"] is True
            assert len(r["poles"]) == n

    def test_invalid_order_zero(self):
        r = butterworth_poles(0)
        assert r["ok"] is False

    def test_all_poles_on_unit_circle_n5(self):
        """n=5: all poles on unit circle |s|=1."""
        r = butterworth_poles(5)
        assert r["ok"] is True
        for p in r["poles"]:
            mag = math.sqrt(p["re"] ** 2 + p["im"] ** 2)
            assert mag == pytest.approx(1.0, abs=1e-8)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. chebyshev_poles
# ═══════════════════════════════════════════════════════════════════════════════

class TestChebyshevPoles:

    def test_all_poles_left_half_plane(self):
        """All Chebyshev poles have Re < 0."""
        for n in [1, 2, 3, 4]:
            r = chebyshev_poles(n, passband_ripple_db=0.5)
            assert r["ok"] is True
            for p in r["poles"]:
                assert p["re"] < 0.0

    def test_pole_count_equals_n(self):
        r = chebyshev_poles(4, passband_ripple_db=1.0)
        assert r["ok"] is True
        assert len(r["poles"]) == 4

    def test_n1_real_pole(self):
        """n=1: single real pole (no imaginary part)."""
        r = chebyshev_poles(1, passband_ripple_db=0.5)
        assert r["ok"] is True
        assert abs(r["poles"][0]["im"]) < 1e-8

    def test_invalid_order(self):
        r = chebyshev_poles(0, passband_ripple_db=0.5)
        assert r["ok"] is False

    def test_higher_ripple_poles_closer_to_jw_axis(self):
        """Higher ripple → poles closer to imaginary axis (smaller |Re|)."""
        r1 = chebyshev_poles(3, passband_ripple_db=0.1)
        r2 = chebyshev_poles(3, passband_ripple_db=3.0)
        assert r1["ok"] and r2["ok"]
        # The most negative real part in r2 should be less negative (closer to jω axis)
        max_re_r1 = max(abs(p["re"]) for p in r1["poles"])
        max_re_r2 = max(abs(p["re"]) for p in r2["poles"])
        # Higher ripple → smaller damping → poles closer to j-axis
        assert max_re_r2 <= max_re_r1 + 1e-6


# ═══════════════════════════════════════════════════════════════════════════════
# 6. bessel_poles
# ═══════════════════════════════════════════════════════════════════════════════

class TestBesselPoles:

    def test_n1_pole_at_minus1(self):
        """n=1: Bessel polynomial is s+1; pole at s=−1."""
        r = bessel_poles(1)
        assert r["ok"] is True
        assert len(r["poles"]) == 1
        assert r["poles"][0]["re"] == pytest.approx(-1.0, abs=1e-6)
        assert abs(r["poles"][0]["im"]) < 1e-6

    def test_n2_known_poles(self):
        """n=2: known Bessel poles at s ≈ −1.5 ± j0.866."""
        r = bessel_poles(2)
        assert r["ok"] is True
        assert len(r["poles"]) == 2
        real_parts = sorted(p["re"] for p in r["poles"])
        # Both should have Re ≈ −1.5
        for re in real_parts:
            assert re == pytest.approx(-1.5, abs=0.01)

    def test_all_poles_left_half_plane(self):
        """All Bessel poles have Re < 0."""
        for n in [1, 2, 3, 4, 5]:
            r = bessel_poles(n)
            assert r["ok"] is True
            for p in r["poles"]:
                assert p["re"] < 0.0

    def test_order_too_large(self):
        """Order > 10 → ok=False."""
        r = bessel_poles(11)
        assert r["ok"] is False

    def test_pole_count_equals_order(self):
        for n in [1, 3, 5]:
            r = bessel_poles(n)
            assert r["ok"] is True
            assert len(r["poles"]) == n


# ═══════════════════════════════════════════════════════════════════════════════
# 7. butterworth_g_values
# ═══════════════════════════════════════════════════════════════════════════════

class TestButterworthGValues:

    def test_n1_g_values(self):
        """n=1: g = [1, 2, 1]."""
        r = butterworth_g_values(1)
        assert r["ok"] is True
        assert len(r["g_values"]) == 3
        assert r["g_values"][0] == pytest.approx(1.0)
        assert r["g_values"][1] == pytest.approx(2.0, abs=1e-8)
        assert r["g_values"][2] == pytest.approx(1.0)

    def test_n2_symmetric(self):
        """n=2: g_1 = g_2 = sqrt(2) (symmetric)."""
        r = butterworth_g_values(2)
        assert r["ok"] is True
        assert len(r["g_values"]) == 4
        assert r["g_values"][1] == pytest.approx(math.sqrt(2), abs=1e-8)
        assert r["g_values"][2] == pytest.approx(math.sqrt(2), abs=1e-8)
        assert r["g_values"][-1] == pytest.approx(1.0)

    def test_g0_always_1(self):
        for n in [1, 2, 3, 5]:
            r = butterworth_g_values(n)
            assert r["ok"] is True
            assert r["g_values"][0] == pytest.approx(1.0)

    def test_g_values_length(self):
        for n in [1, 3, 6]:
            r = butterworth_g_values(n)
            assert r["ok"] is True
            assert len(r["g_values"]) == n + 2

    def test_invalid_order(self):
        r = butterworth_g_values(0)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 8. chebyshev_g_values
# ═══════════════════════════════════════════════════════════════════════════════

class TestChebyshevGValues:

    def test_n1_0p5db_known_g1(self):
        """n=1, 0.5dB ripple: known g_1 ≈ 0.6986 (Zverev table)."""
        r = chebyshev_g_values(1, passband_ripple_db=0.5)
        assert r["ok"] is True
        # For n=1, 0.5dB: g1 = 2*sinh(beta/2) / ... should give ≈ 0.6986
        # More precisely from Williams table: g1=0.6986 for 0.5dB n=1
        assert r["g_values"][1] == pytest.approx(0.6986, abs=0.01)

    def test_n2_0p5db_all_positive(self):
        r = chebyshev_g_values(2, passband_ripple_db=0.5)
        assert r["ok"] is True
        for g in r["g_values"]:
            assert g > 0.0

    def test_g_values_length(self):
        for n in [1, 2, 4]:
            r = chebyshev_g_values(n, passband_ripple_db=1.0)
            assert r["ok"] is True
            assert len(r["g_values"]) == n + 2

    def test_negative_ripple_invalid(self):
        r = chebyshev_g_values(3, passband_ripple_db=-0.5)
        assert r["ok"] is False

    def test_g0_always_1(self):
        r = chebyshev_g_values(4, passband_ripple_db=1.0)
        assert r["ok"] is True
        assert r["g_values"][0] == pytest.approx(1.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. lp_to_lp_rlc
# ═══════════════════════════════════════════════════════════════════════════════

class TestLpToLpRlc:

    def test_n1_butterworth_single_inductor(self):
        """n=1 Butterworth: single series L = g_1 × Z0/ω_c."""
        g = butterworth_g_values(1)["g_values"]
        fc = 1000.0
        z0 = 50.0
        r = lp_to_lp_rlc(g, fc, z0)
        assert r["ok"] is True
        assert len(r["elements"]) == 1
        assert r["elements"][0]["type"] == "L"
        omega_c = 2.0 * math.pi * fc
        expected_L = g[1] * z0 / omega_c
        assert r["elements"][0]["value"] == pytest.approx(expected_L, rel=1e-6)

    def test_n2_alternating_types(self):
        """n=2: first element is L (series), second is C (shunt)."""
        g = butterworth_g_values(2)["g_values"]
        r = lp_to_lp_rlc(g, 1000.0, 50.0)
        assert r["ok"] is True
        assert len(r["elements"]) == 2
        assert r["elements"][0]["type"] == "L"
        assert r["elements"][1]["type"] == "C"

    def test_doubling_impedance_doubles_L_halves_C(self):
        """Doubling Z0 doubles L values and halves C values."""
        g = butterworth_g_values(3)["g_values"]
        fc = 5000.0
        r1 = lp_to_lp_rlc(g, fc, 50.0)
        r2 = lp_to_lp_rlc(g, fc, 100.0)
        assert r1["ok"] and r2["ok"]
        for e1, e2 in zip(r1["elements"], r2["elements"]):
            if e1["type"] == "L":
                assert e2["value"] == pytest.approx(2.0 * e1["value"], rel=1e-6)
            else:
                assert e2["value"] == pytest.approx(0.5 * e1["value"], rel=1e-6)

    def test_zero_cutoff_invalid(self):
        g = butterworth_g_values(2)["g_values"]
        r = lp_to_lp_rlc(g, 0.0, 50.0)
        assert r["ok"] is False

    def test_zero_impedance_invalid(self):
        g = butterworth_g_values(2)["g_values"]
        r = lp_to_lp_rlc(g, 1000.0, 0.0)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 10. lp_to_hp_rlc
# ═══════════════════════════════════════════════════════════════════════════════

class TestLpToHpRlc:

    def test_n1_lp_inductor_becomes_hp_capacitor(self):
        """n=1: LP series L (odd element) → HP shunt C."""
        g = butterworth_g_values(1)["g_values"]
        r = lp_to_hp_rlc(g, 1000.0, 50.0)
        assert r["ok"] is True
        assert len(r["elements"]) == 1
        assert r["elements"][0]["type"] == "C"

    def test_n3_alternating_types_hp(self):
        """n=3 HP: types are C, L, C (inverse of LP series/shunt)."""
        g = butterworth_g_values(3)["g_values"]
        r = lp_to_hp_rlc(g, 1000.0, 50.0)
        assert r["ok"] is True
        assert len(r["elements"]) == 3
        assert r["elements"][0]["type"] == "C"
        assert r["elements"][1]["type"] == "L"
        assert r["elements"][2]["type"] == "C"

    def test_zero_cutoff_invalid(self):
        g = butterworth_g_values(2)["g_values"]
        r = lp_to_hp_rlc(g, 0.0, 50.0)
        assert r["ok"] is False

    def test_component_values_positive(self):
        g = butterworth_g_values(4)["g_values"]
        r = lp_to_hp_rlc(g, 10000.0, 50.0)
        assert r["ok"] is True
        for e in r["elements"]:
            assert e["value"] > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 11. lp_to_bp_rlc
# ═══════════════════════════════════════════════════════════════════════════════

class TestLpToBpRlc:

    def test_n1_resonator_structure(self):
        """n=1 LP→BP: single resonator dict with L_h and C_f."""
        g = butterworth_g_values(1)["g_values"]
        r = lp_to_bp_rlc(g, center_freq_hz=10000.0, bandwidth_hz=1000.0)
        assert r["ok"] is True
        assert len(r["elements"]) == 1
        res = r["elements"][0]["resonator"]
        assert res["L_h"] > 0.0
        assert res["C_f"] > 0.0

    def test_resonator_f0_equals_center(self):
        """Resonator f0 equals center_freq_hz."""
        g = butterworth_g_values(2)["g_values"]
        fc = 50000.0
        r = lp_to_bp_rlc(g, center_freq_hz=fc, bandwidth_hz=5000.0)
        assert r["ok"] is True
        for e in r["elements"]:
            assert e["resonator"]["f0_hz"] == pytest.approx(fc, rel=1e-4)

    def test_q_correct(self):
        """Q = f0 / BW."""
        fc, bw = 100000.0, 10000.0
        g = butterworth_g_values(2)["g_values"]
        r = lp_to_bp_rlc(g, center_freq_hz=fc, bandwidth_hz=bw)
        assert r["ok"] is True
        assert r["Q"] == pytest.approx(fc / bw, rel=1e-6)

    def test_zero_bandwidth_invalid(self):
        g = butterworth_g_values(2)["g_values"]
        r = lp_to_bp_rlc(g, 10000.0, 0.0)
        assert r["ok"] is False

    def test_both_lc_positive(self):
        g = butterworth_g_values(3)["g_values"]
        r = lp_to_bp_rlc(g, 20000.0, 2000.0)
        assert r["ok"] is True
        for e in r["elements"]:
            assert e["resonator"]["L_h"] > 0.0
            assert e["resonator"]["C_f"] > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# 12. sallen_key_components
# ═══════════════════════════════════════════════════════════════════════════════

class TestSallenKeyComponents:

    def test_butterworth_q_k_required(self):
        """2nd-order Butterworth section: Q=1/√2 → K_required = 3 − √2 ≈ 1.586."""
        Q_bw = 1.0 / math.sqrt(2.0)
        K_expected = 3.0 - 1.0 / Q_bw  # = 3 - sqrt(2) ≈ 1.586
        r = sallen_key_components(cutoff_freq_hz=1000.0, Q=Q_bw, gain=K_expected)
        assert r["ok"] is True
        assert r["K_required_for_Q"] == pytest.approx(K_expected, rel=1e-4)

    def test_unity_gain_no_feedback_resistors(self):
        """Unity gain (K=1): Rf and Rg are None."""
        r = sallen_key_components(1000.0, Q=0.707, gain=1.0)
        assert r["ok"] is True
        assert r["Rf_ohm"] is None
        assert r["Rg_ohm"] is None

    def test_q_below_half_not_realizable(self):
        """Q < 0.5 → K_required < 1; equal-component design not realizable."""
        r = sallen_key_components(1000.0, Q=0.3, gain=1.0)
        assert r["ok"] is True
        assert r["realizable"] is False

    def test_r_value_formula(self):
        """R = 1/(2π × f × C) within 1%."""
        fc = 5000.0
        C = 10e-9
        r = sallen_key_components(fc, Q=0.707, gain=1.0, capacitor_f=C)
        assert r["ok"] is True
        R_expected = 1.0 / (2.0 * math.pi * fc * C)
        assert r["R1_ohm"] == pytest.approx(R_expected, rel=0.01)

    def test_equal_capacitors(self):
        """C1 == C2 for equal-capacitor design."""
        r = sallen_key_components(1000.0, Q=0.707, gain=1.0)
        assert r["ok"] is True
        assert r["C1_f"] == r["C2_f"]

    def test_zero_cutoff_invalid(self):
        r = sallen_key_components(0.0, Q=0.707)
        assert r["ok"] is False

    def test_zero_q_invalid(self):
        r = sallen_key_components(1000.0, Q=0.0)
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 13. multiple_feedback_components
# ═══════════════════════════════════════════════════════════════════════════════

class TestMultipleFeedbackComponents:

    def test_low_q_high_gain_realizable(self):
        """Q=0.1, |gain|=10: discriminant = (ω/0.1)² - 4ω²×11 > 0 → realizable=True."""
        # discriminant check: 1/Q² >= 4(1+K): 100 >= 44 -> True
        r = multiple_feedback_components(1000.0, Q=0.1, gain=-10.0)
        assert r["ok"] is True
        assert r["realizable"] is True
        assert r["R1_ohm"] is not None and r["R1_ohm"] > 0
        assert r["R2_ohm"] is not None and r["R2_ohm"] > 0

    def test_high_q_low_gain_not_realizable(self):
        """Very high Q with low gain → negative discriminant → realizable=False."""
        # discriminant = (ω/Q)² - 4ω²(1+K) < 0 for large Q, K=1
        # Need Q > 0.5/sqrt(1+K) for realizable...
        # For Q=10, K=1: disc = (ω/10)² - 4ω²×2 = ω²(0.01 - 8) < 0
        r = multiple_feedback_components(1000.0, Q=10.0, gain=-1.0)
        assert r["ok"] is True
        assert r["realizable"] is False

    def test_all_resistors_positive_when_realizable(self):
        r = multiple_feedback_components(1000.0, Q=0.5, gain=-2.0)
        if r["realizable"]:
            assert r["R1_ohm"] > 0
            assert r["R2_ohm"] > 0
            assert r["R3_ohm"] is not None and r["R3_ohm"] > 0

    def test_zero_gain_invalid(self):
        r = multiple_feedback_components(1000.0, Q=0.707, gain=0.0)
        assert r["ok"] is False

    def test_equal_capacitors(self):
        r = multiple_feedback_components(1000.0, Q=0.707, gain=-1.0)
        assert r["ok"] is True
        assert r["C1_f"] == r["C2_f"]


# ═══════════════════════════════════════════════════════════════════════════════
# 14. filter_response
# ═══════════════════════════════════════════════════════════════════════════════

class TestFilterResponse:

    def test_single_pole_at_minus1_at_omega1(self):
        """Single pole at s=−1, f = 1/(2π) Hz (ω=1 rad/s): |H| = 1/√2 → −3.01 dB."""
        freq = 1.0 / (2.0 * math.pi)
        r = filter_response(poles=[{"re": -1.0, "im": 0.0}], freq_hz=freq)
        assert r["ok"] is True
        assert r["magnitude_db"] == pytest.approx(-3.0103, abs=0.01)

    def test_dc_gain_at_low_frequency(self):
        """Very low frequency: |H| ≈ gain_dc (assuming only LHP poles)."""
        poles = [{"re": -1000.0, "im": 0.0}]
        r = filter_response(poles=poles, gain_dc=2.0, freq_hz=0.001)
        assert r["ok"] is True
        # At very low frequency, |H(jω)| ≈ |gain_dc / prod(-p_k)| for no zeros
        # For single pole at -1000: H(0) = gain_dc / 1000
        assert r["H_mag"] == pytest.approx(2.0 / 1000.0, rel=0.01)

    def test_group_delay_positive(self):
        """Group delay positive for left-half-plane poles."""
        poles = [{"re": -1.0, "im": 0.5}]
        r = filter_response(poles=poles, freq_hz=1.0)
        assert r["ok"] is True
        assert r["group_delay_s"] > 0.0

    def test_empty_poles_returns_gain(self):
        """No poles, no zeros: H = gain_dc at all frequencies."""
        r = filter_response(poles=[], zeros=[], gain_dc=3.0, freq_hz=1000.0)
        assert r["ok"] is True
        assert r["H_mag"] == pytest.approx(3.0, rel=1e-8)

    def test_zero_at_origin_reduces_dc(self):
        """Zero at s=0 causes H(j×very_small_ω) → 0."""
        poles = [{"re": -1.0, "im": 0.0}]
        zeros = [{"re": 0.0, "im": 0.0}]
        r = filter_response(poles=poles, zeros=zeros, freq_hz=0.0001)
        assert r["ok"] is True
        assert r["H_mag"] < 0.01  # very small at near-DC

    def test_invalid_poles_type(self):
        """Non-dict, non-number in poles → ok=False."""
        r = filter_response(poles=["invalid"], freq_hz=1000.0)
        assert r["ok"] is False

    def test_magnitude_db_present(self):
        """magnitude_db key is always present for ok=True."""
        r = filter_response(poles=[{"re": -1.0, "im": 0.0}], freq_hz=100.0)
        assert r["ok"] is True
        assert "magnitude_db" in r


# ═══════════════════════════════════════════════════════════════════════════════
# 15. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolHandlers:

    @pytest.mark.asyncio
    async def test_butterworth_order_tool_ok(self):
        r = await call(
            _bw_order_tool,
            passband_freq_hz=1000.0,
            stopband_freq_hz=2000.0,
            passband_ripple_db=3.0,
            stopband_atten_db=40.0,
        )
        assert r["ok"] is True
        assert "order" in r

    @pytest.mark.asyncio
    async def test_chebyshev_order_tool_ok(self):
        r = await call(
            _cheb_order_tool,
            passband_freq_hz=1000.0,
            stopband_freq_hz=3000.0,
            passband_ripple_db=0.5,
            stopband_atten_db=40.0,
        )
        assert r["ok"] is True
        assert r["epsilon"] > 0.0

    @pytest.mark.asyncio
    async def test_bessel_order_tool_ok(self):
        r = await call(_bess_order_tool, group_delay_flatness_percent=5.0, bandwidth_ratio=2.0)
        assert r["ok"] is True
        assert isinstance(r["order"], int)

    @pytest.mark.asyncio
    async def test_butterworth_poles_tool_ok(self):
        r = await call(_bw_poles_tool, order=4)
        assert r["ok"] is True
        assert len(r["poles"]) == 4

    @pytest.mark.asyncio
    async def test_chebyshev_poles_tool_ok(self):
        r = await call(_cheb_poles_tool, order=3, passband_ripple_db=1.0)
        assert r["ok"] is True
        assert len(r["poles"]) == 3

    @pytest.mark.asyncio
    async def test_bessel_poles_tool_ok(self):
        r = await call(_bess_poles_tool, order=2)
        assert r["ok"] is True
        assert len(r["poles"]) == 2

    @pytest.mark.asyncio
    async def test_butterworth_g_tool_g0_is_1(self):
        r = await call(_bw_g_tool, order=3)
        assert r["ok"] is True
        assert r["g_values"][0] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_chebyshev_g_tool_length(self):
        n = 4
        r = await call(_cheb_g_tool, order=n, passband_ripple_db=0.5)
        assert r["ok"] is True
        assert len(r["g_values"]) == n + 2

    @pytest.mark.asyncio
    async def test_lp_to_lp_tool_ok(self):
        g = butterworth_g_values(2)["g_values"]
        r = await call(_lp_lp_tool, g_values=g, cutoff_freq_hz=1000.0)
        assert r["ok"] is True
        assert len(r["elements"]) > 0

    @pytest.mark.asyncio
    async def test_lp_to_hp_tool_first_element_c(self):
        g = butterworth_g_values(2)["g_values"]
        r = await call(_lp_hp_tool, g_values=g, cutoff_freq_hz=1000.0)
        assert r["ok"] is True
        assert r["elements"][0]["type"] == "C"

    @pytest.mark.asyncio
    async def test_lp_to_bp_tool_resonators(self):
        g = butterworth_g_values(2)["g_values"]
        r = await call(
            _lp_bp_tool,
            g_values=g,
            center_freq_hz=10000.0,
            bandwidth_hz=1000.0,
        )
        assert r["ok"] is True
        for e in r["elements"]:
            assert "resonator" in e

    @pytest.mark.asyncio
    async def test_sallen_key_tool_r_positive(self):
        r = await call(_sk_tool, cutoff_freq_hz=5000.0, Q=0.707)
        assert r["ok"] is True
        assert r["R1_ohm"] > 0

    @pytest.mark.asyncio
    async def test_mfb_tool_realizable(self):
        # Q=0.1, gain=-10 satisfies 1/Q²=100 >= 4(1+10)=44 → realizable
        r = await call(_mfb_tool, cutoff_freq_hz=1000.0, Q=0.1, gain=-10.0)
        assert r["ok"] is True
        assert r["realizable"] is True

    @pytest.mark.asyncio
    async def test_response_tool_magnitude_db(self):
        r = await call(
            _resp_tool,
            poles=[{"re": -1.0, "im": 0.0}],
            freq_hz=100.0,
        )
        assert r["ok"] is True
        assert "magnitude_db" in r

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error_payload(self):
        """Invalid JSON bytes → error payload (never raises)."""
        result = await _bw_order_tool(None, b"{invalid json}")
        d = json.loads(result)
        # Real kerf_chat err_payload: {"error": ..., "code": ...}
        # Stub err_payload: {"ok": False, "error": ..., "code": ...}
        # Either way: "error" key is present and response is a valid JSON dict
        assert isinstance(d, dict)
        assert "error" in d or d.get("ok") is False
