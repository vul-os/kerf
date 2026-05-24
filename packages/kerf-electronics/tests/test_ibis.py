"""
Tests for IBIS parser and channel simulator.

Covers:
  - ibis_parser.py  — parse_ibis(), ibis_deck_to_dict()
  - ibis_channel.py — channel_response(), eye_diagram_envelope()
  - tools/si_ibis.py — si_ibis_parse and si_ibis_channel_response LLM tools

IBIS spec targeted: IBIS 5.1 (keyword/subkeyword grammar).

Author: imranparuk
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import types

import pytest

# ── Stub kerf_chat registry (same pattern as test_si.py) ─────────────────────

try:
    import kerf_chat as _kc_pkg  # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type("ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)})
_reg_stub.err_payload = lambda msg, code: json.dumps({"error": msg, "code": code})
_reg_stub.ok_payload = lambda v: json.dumps(v)
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kerf_chat_stub = types.ModuleType("kerf_chat")
_kerf_chat_tools_stub = types.ModuleType("kerf_chat.tools")

sys.modules.setdefault("kerf_chat", _kerf_chat_stub)
sys.modules.setdefault("kerf_chat.tools", _kerf_chat_tools_stub)
_KERF_CHAT_SAVED = {
    _n: sys.modules.get(_n)
    for _n in ("kerf_chat", "kerf_chat.tools", "kerf_chat.tools.registry")
}
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub


# ── Load modules from file paths ──────────────────────────────────────────────

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_base = "packages/kerf-electronics/src/kerf_electronics"

_compat = _load("kerf_electronics._compat", f"{_base}/_compat.py")

# Expose ke stub so sub-imports resolve
_ke_stub = types.ModuleType("kerf_electronics")
_ke_si_stub = types.ModuleType("kerf_electronics.si")
_ke_tools_stub = types.ModuleType("kerf_electronics.tools")
sys.modules.setdefault("kerf_electronics", _ke_stub)
sys.modules.setdefault("kerf_electronics.si", _ke_si_stub)
sys.modules.setdefault("kerf_electronics.tools", _ke_tools_stub)
sys.modules["kerf_electronics._compat"] = _compat

_ibis_parser = _load(
    "kerf_electronics.si.ibis_parser",
    f"{_base}/si/ibis_parser.py",
)
sys.modules["kerf_electronics.si.ibis_parser"] = _ibis_parser

_ibis_channel = _load(
    "kerf_electronics.si.ibis_channel",
    f"{_base}/si/ibis_channel.py",
)
sys.modules["kerf_electronics.si.ibis_channel"] = _ibis_channel

_tool_ibis = _load(
    "kerf_electronics.tools.si_ibis",
    f"{_base}/tools/si_ibis.py",
)

parse_ibis = _ibis_parser.parse_ibis
ibis_deck_to_dict = _ibis_parser.ibis_deck_to_dict
IBISParseError = _ibis_parser.IBISParseError
channel_response = _ibis_channel.channel_response
eye_diagram_envelope = _ibis_channel.eye_diagram_envelope

si_ibis_parse = _tool_ibis.si_ibis_parse
si_ibis_channel_response = _tool_ibis.si_ibis_channel_response


# ── Async helper ──────────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ── Synthetic IBIS file ───────────────────────────────────────────────────────

# A minimal but structurally complete IBIS 5.x file for a 3.3 V CMOS output.
SYNTHETIC_IBS = """\
[IBIS Ver]      5.1
[File Name]     test_synth.ibs
[File Rev]      0.1
[Date]          2026-05-24
[Source]        kerf-electronics test suite
[Disclaimer]    For SI testing only.

[Component]     TestChip
[Manufacturer]  Acme Devices
[Package]
R_pkg     0.5     0.4     0.6
L_pkg     3n      2n      4n
C_pkg     0.5p    0.3p    0.7p
[Pin]  signal_name        model_name
1      DATA_OUT            out_3v3
2      DATA_IN             in_3v3
[End]

[Model]         out_3v3
Model_type      Output
Polarity        Non-Inverting
C_comp          4p      3p      5p

[Pulldown]
| Voltage    I(typ)    I(min)    I(max)
-3.3        -66m      -55m      -77m
0.0          0.0       0.0       0.0
0.5          10m       8m        12m
1.0          20m       16m       24m
1.65         28m       22m       34m
2.5          32m       25m       38m
3.3          35m       28m       42m
6.6          36m       30m       43m

[Pullup]
| Voltage    I(typ)    I(min)    I(max)
-3.3         66m       55m       77m
0.0           0.0       0.0       0.0
0.5         -10m       -8m      -12m
1.0         -20m      -16m      -24m
1.65        -28m      -22m      -34m
2.5         -32m      -25m      -38m
3.3         -35m      -28m      -42m
6.6         -36m      -30m      -43m

[Ramp]
R_load       50
dv/dt_r      1.98V/1.0ns    1.5V/1.1ns    2.3V/0.9ns
dv/dt_f      1.98V/1.0ns    1.5V/1.1ns    2.3V/0.9ns

[Rising Waveform]
R_fixture     50
V_fixture     3.3
| time       V(typ)    V(min)    V(max)
0.0          0.0       0.0       0.0
0.5n         0.99      0.75      1.15
1.0n         1.98      1.50      2.30
1.5n         2.50      2.00      2.90
2.0n         3.1       2.7       3.2
3.0n         3.3       3.0       3.3

[Falling Waveform]
R_fixture     50
V_fixture     0.0
| time       V(typ)    V(min)    V(max)
0.0          3.3       3.3       3.3
0.5n         2.31      2.55      2.15
1.0n         1.32      1.80      0.97
1.5n         0.8       1.3       0.4
2.0n         0.2       0.6       0.1
3.0n         0.0       0.3       0.0

[Model]         in_3v3
Model_type      Input
Polarity        Non-Inverting
C_comp          2p      1.5p    2.5p

[End]
"""


# ═════════════════════════════════════════════════════════════════════════════
# Parser unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestIBISParser:
    """Validate parse_ibis() on the synthetic IBIS file."""

    def _deck(self):
        return parse_ibis(SYNTHETIC_IBS)

    def test_ibis_ver_parsed(self):
        deck = self._deck()
        assert "5.1" in deck.ibis_ver

    def test_file_name_parsed(self):
        deck = self._deck()
        assert "test_synth.ibs" in deck.file_name

    def test_component_present(self):
        deck = self._deck()
        assert len(deck.components) == 1
        assert deck.components[0].name == "TestChip"

    def test_manufacturer_parsed(self):
        deck = self._deck()
        comp = deck.components[0]
        assert "Acme" in comp.manufacturer

    def test_package_r_parsed(self):
        deck = self._deck()
        comp = deck.components[0]
        assert comp.package_r.typ == pytest.approx(0.5, rel=1e-3)
        assert comp.package_r.min == pytest.approx(0.4, rel=1e-3)
        assert comp.package_r.max == pytest.approx(0.6, rel=1e-3)

    def test_package_l_parsed(self):
        deck = self._deck()
        comp = deck.components[0]
        # 3n = 3e-9
        assert comp.package_l.typ == pytest.approx(3e-9, rel=1e-3)

    def test_package_c_parsed(self):
        deck = self._deck()
        comp = deck.components[0]
        # 0.5p = 0.5e-12
        assert comp.package_c.typ == pytest.approx(0.5e-12, rel=1e-3)

    def test_pin_count(self):
        deck = self._deck()
        comp = deck.components[0]
        assert len(comp.pins) == 2

    def test_pin_names(self):
        deck = self._deck()
        pins = {p.pin_name: p for p in deck.components[0].pins}
        assert "1" in pins
        assert pins["1"].signal_name == "DATA_OUT"
        assert pins["1"].model_name == "out_3v3"

    def test_two_models_parsed(self):
        deck = self._deck()
        assert len(deck.models) == 2

    def test_output_model_present(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        assert m is not None
        assert m.model_type == "Output"
        assert m.polarity == "Non-Inverting"

    def test_input_model_present(self):
        deck = self._deck()
        m = deck.model("in_3v3")
        assert m is not None
        assert m.model_type == "Input"

    def test_c_comp_parsed_with_si_suffix(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        assert m.c_comp.typ == pytest.approx(4e-12, rel=1e-3)
        assert m.c_comp.min == pytest.approx(3e-12, rel=1e-3)
        assert m.c_comp.max == pytest.approx(5e-12, rel=1e-3)

    def test_pulldown_table_row_count(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        # 8 data rows in the synthetic table
        assert len(m.pulldown) == 8

    def test_pulldown_iv_round_trip(self):
        """Pulldown IV values survive the parse round-trip exactly."""
        deck = self._deck()
        m = deck.model("out_3v3")
        # Row at V=0: (0.0, 0.0, 0.0, 0.0)
        zero_row = next(r for r in m.pulldown if abs(r[0]) < 1e-9)
        assert zero_row[1] == pytest.approx(0.0, abs=1e-12)

        # Row at V=1.0: I_typ = 20m = 0.020 A
        row_1v = next(r for r in m.pulldown if abs(r[0] - 1.0) < 1e-6)
        assert row_1v[1] == pytest.approx(0.020, rel=1e-3)
        assert row_1v[2] == pytest.approx(0.016, rel=1e-3)
        assert row_1v[3] == pytest.approx(0.024, rel=1e-3)

    def test_pulldown_negative_voltage_row(self):
        """Negative voltage rows (V = -3.3) are parsed correctly."""
        deck = self._deck()
        m = deck.model("out_3v3")
        neg_row = next(r for r in m.pulldown if r[0] < -3.0)
        assert neg_row[0] == pytest.approx(-3.3, rel=1e-3)
        assert neg_row[1] == pytest.approx(-0.066, rel=1e-3)

    def test_pullup_table_present(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        assert len(m.pullup) == 8
        zero_row = next(r for r in m.pullup if abs(r[0]) < 1e-9)
        assert zero_row[1] == pytest.approx(0.0, abs=1e-12)

    def test_ramp_parsed(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        assert m.ramp is not None
        assert m.ramp.r_load == pytest.approx(50.0, rel=1e-3)

    def test_ramp_dvdt_rise_typ(self):
        """dV/dt rise typ = 1.98V / 1.0ns = 1.98e9 V/s."""
        deck = self._deck()
        m = deck.model("out_3v3")
        assert m.ramp.dv_dt_rise.typ == pytest.approx(1.98e9, rel=1e-3)

    def test_ramp_dvdt_rise_corners(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        # min = 1.5V/1.1ns ≈ 1.364e9
        assert m.ramp.dv_dt_rise.min == pytest.approx(1.5e9 / 1.1, rel=0.01)
        # max = 2.3V/0.9ns ≈ 2.556e9
        assert m.ramp.dv_dt_rise.max == pytest.approx(2.3e9 / 0.9, rel=0.01)

    def test_rising_waveform_present(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        assert len(m.rising_waveforms) == 1
        wf = m.rising_waveforms[0]
        assert wf.r_fixture == pytest.approx(50.0, rel=1e-3)
        assert wf.v_fixture == pytest.approx(3.3, rel=1e-3)
        assert len(wf.table) == 6

    def test_rising_waveform_table_values(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        wf = m.rising_waveforms[0]
        # Row at t=0.5n: V_typ = 0.99
        row = next(r for r in wf.table if abs(r[0] - 0.5e-9) < 1e-12)
        assert row[1] == pytest.approx(0.99, rel=1e-3)

    def test_falling_waveform_present(self):
        deck = self._deck()
        m = deck.model("out_3v3")
        assert len(m.falling_waveforms) == 1

    def test_component_lookup_case_insensitive(self):
        deck = self._deck()
        assert deck.component("testchip") is not None
        assert deck.component("TESTCHIP") is not None

    def test_model_lookup_case_insensitive(self):
        deck = self._deck()
        assert deck.model("OUT_3V3") is not None

    def test_empty_text_raises(self):
        with pytest.raises(IBISParseError):
            parse_ibis("")

    def test_dict_round_trip(self):
        """ibis_deck_to_dict produces a JSON-serialisable dict."""
        deck = self._deck()
        d = ibis_deck_to_dict(deck)
        # Must be JSON-round-trippable
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2["ibis_ver"] == d["ibis_ver"]
        assert len(d2["models"]) == 2
        # Pulldown rows preserved
        pd = d2["models"][0]["pulldown"]
        row_1v = next(r for r in pd if abs(r[0] - 1.0) < 1e-6)
        assert row_1v[1] == pytest.approx(0.020, rel=1e-3)

    def test_unknown_keyword_reported(self):
        ibs = SYNTHETIC_IBS + "\n[Zap Frob]  some unknown keyword\n"
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            deck = parse_ibis(ibs)
        assert "Zap Frob" in deck.unknown_keywords


# ═════════════════════════════════════════════════════════════════════════════
# Channel simulation unit tests
# ═════════════════════════════════════════════════════════════════════════════

def _make_model():
    """Build a clean IBISModel from the synthetic IBIS for channel tests."""
    deck = parse_ibis(SYNTHETIC_IBS)
    return deck.model("out_3v3")


class TestSIChannel:
    """Validate channel_response() physics."""

    def test_returns_list_of_tuples(self):
        model = _make_model()
        wave = channel_response(model, z0=50, length_m=0.1, er=4.2, r_term=50)
        assert isinstance(wave, list)
        assert len(wave) > 0
        t, v = wave[0]
        assert isinstance(t, float)
        assert isinstance(v, float)

    def test_waveform_starts_at_zero(self):
        """Receiver starts at low state (approx v_ol)."""
        model = _make_model()
        wave = channel_response(model, z0=50, length_m=0.1, er=4.2, r_term=50)
        t0, v0 = wave[0]
        assert t0 == pytest.approx(0.0, abs=1e-12)
        assert v0 < 0.5  # should be near v_ol ~ 0.2 V

    def test_waveform_reaches_high_eventually(self):
        """Receiver must exceed 1 V after the bit period on a matched 50Ω line."""
        model = _make_model()
        wave = channel_response(model, z0=50, length_m=0.1, er=4.2, r_term=50)
        max_v = max(v for _, v in wave)
        assert max_v > 1.0, f"Expected waveform to reach high; max_v={max_v:.3f}"

    def test_matched_line_delay_fr4_100mm(self):
        """
        50Ω matched, lossless, 100mm FR-4 (er=4.2) line.
        One-way delay TD = 0.1 * sqrt(4.2) / c ≈ 0.684 ns.
        The waveform should show the ramp starting at approximately TD.
        Verify: V(0.3 ns) ≈ low, V(1.5 ns) is rising.
        """
        model = _make_model()
        wave = channel_response(
            model, z0=50, length_m=0.1, er=4.2, r_term=50,
            v_supply=3.3, n_pts=1000,
        )

        _C = 2.997924580e8
        td_s = 0.1 * math.sqrt(4.2) / _C
        td_ns = td_s * 1e9  # ≈ 0.684 ns

        # Before delay: still low
        t_early_s = td_s * 0.3
        v_early = _sample_wave(wave, t_early_s)
        assert v_early < 0.5, (
            f"Receiver should be low before TD; V({t_early_s*1e9:.2f} ns)={v_early:.3f}"
        )

        # After 2 × TD the high state should be settling
        t_late_s = td_s * 3.0
        v_late = _sample_wave(wave, t_late_s)
        assert v_late > 0.5, (
            f"Receiver should be rising/high after delay; V({t_late_s*1e9:.2f} ns)={v_late:.3f}"
        )

    def test_delay_approximately_half_ns_at_100mm_fr4(self):
        """
        The propagation delay for 100mm FR-4 (er=4.2) is:
            TD = 0.1 m * sqrt(4.2) / 3e8 ≈ 0.684 ns ≈ 0.5-0.9 ns range.
        Verify it falls in [0.4, 1.0] ns.
        """
        _C = 2.997924580e8
        td_ns = 0.1 * math.sqrt(4.2) / _C * 1e9
        assert 0.4 < td_ns < 1.0, f"TD should be ~0.68 ns, got {td_ns:.3f} ns"

    def test_mismatch_causes_reflection(self):
        """
        High mismatch (Z_term=200Ω on 50Ω line) should show overshoot
        (reflection visible as V_max > V_oh).
        Matched (50Ω) line should show less overshoot.
        """
        model = _make_model()
        wave_matched = channel_response(
            model, z0=50, length_m=0.1, er=4.2, r_term=50, n_pts=800)
        wave_mismatched = channel_response(
            model, z0=50, length_m=0.1, er=4.2, r_term=200, n_pts=800)

        max_matched = max(v for _, v in wave_matched)
        max_mismatched = max(v for _, v in wave_mismatched)

        # Mismatch should produce higher peak (positive reflection, Γ=(200-50)/(200+50)=0.6)
        assert max_mismatched > max_matched, (
            f"Mismatch peak {max_mismatched:.3f} V not greater than "
            f"matched peak {max_matched:.3f} V"
        )

    def test_reflection_coefficient_matches(self):
        """Reflection coefficient for Z_term=200, Z0=50 should be 0.6."""
        gamma = (200 - 50) / (200 + 50)
        assert gamma == pytest.approx(0.6, rel=1e-6)

    def test_lossless_vs_lossy(self):
        """Lossy line should have lower received amplitude."""
        model = _make_model()
        wave_lossless = channel_response(
            model, z0=50, length_m=0.5, er=4.2, r_term=50,
            alpha_db_per_m=0.0, n_pts=400)
        wave_lossy = channel_response(
            model, z0=50, length_m=0.5, er=4.2, r_term=50,
            alpha_db_per_m=10.0, n_pts=400)

        max_lossless = max(v for _, v in wave_lossless)
        max_lossy = max(v for _, v in wave_lossy)
        assert max_lossless > max_lossy, "Lossy line should attenuate the signal"

    def test_c_term_slows_edge(self):
        """Adding C_term should slow the rising edge at the receiver."""
        model = _make_model()
        wave_fast = channel_response(
            model, z0=50, length_m=0.1, er=4.2, r_term=50,
            c_term_f=0.0, n_pts=500)
        wave_slow = channel_response(
            model, z0=50, length_m=0.1, er=4.2, r_term=50,
            c_term_f=10e-12, n_pts=500)

        # Find the time to reach 1.5 V
        t_fast = _time_to_v(wave_fast, 1.5)
        t_slow = _time_to_v(wave_slow, 1.5)
        assert t_slow > t_fast, "C_term should slow edge: t_slow > t_fast"


class TestEyeDiagram:
    """Validate eye_diagram_envelope()."""

    def test_returns_two_floats(self):
        model = _make_model()
        v_hi, v_lo = eye_diagram_envelope(model, z0=50, length_m=0.1, er=4.2, r_term=50)
        assert isinstance(v_hi, float)
        assert isinstance(v_lo, float)

    def test_eye_high_above_eye_low(self):
        model = _make_model()
        v_hi, v_lo = eye_diagram_envelope(model, z0=50, length_m=0.1, er=4.2, r_term=50)
        assert v_hi > v_lo, f"Eye should be open: v_hi={v_hi:.3f} > v_lo={v_lo:.3f}"

    def test_eye_positive_height(self):
        model = _make_model()
        v_hi, v_lo = eye_diagram_envelope(model, z0=50, length_m=0.1, er=4.2, r_term=50)
        assert (v_hi - v_lo) > 0


# ═════════════════════════════════════════════════════════════════════════════
# LLM tool tests
# ═════════════════════════════════════════════════════════════════════════════

class TestSiIbisParsTool:
    """Tests for the si_ibis_parse LLM tool."""

    @pytest.mark.asyncio
    async def test_parses_synthetic_file(self):
        r = await call(si_ibis_parse, ibs_text=SYNTHETIC_IBS)
        assert "error" not in r
        assert r["ibis_ver"].startswith("5") or "5.1" in r["ibis_ver"]
        assert len(r["models"]) == 2

    @pytest.mark.asyncio
    async def test_pulldown_iv_in_output(self):
        r = await call(si_ibis_parse, ibs_text=SYNTHETIC_IBS)
        out_model = next(m for m in r["models"] if m["name"] == "out_3v3")
        pd = out_model["pulldown"]
        # Find row at V=1.0
        row = next(r for r in pd if abs(r[0] - 1.0) < 1e-6)
        assert row[1] == pytest.approx(0.020, rel=1e-3)

    @pytest.mark.asyncio
    async def test_empty_text_returns_error(self):
        r = await call(si_ibis_parse, ibs_text="   ")
        assert "error" in r

    @pytest.mark.asyncio
    async def test_missing_ibs_text_returns_error(self):
        r = await call(si_ibis_parse)
        assert "error" in r

    @pytest.mark.asyncio
    async def test_ramp_in_output(self):
        r = await call(si_ibis_parse, ibs_text=SYNTHETIC_IBS)
        out_model = next(m for m in r["models"] if m["name"] == "out_3v3")
        assert out_model["ramp"] is not None
        # typ dV/dt ≈ 1.98e9 V/s
        assert out_model["ramp"]["dv_dt_rise"][0] == pytest.approx(1.98e9, rel=1e-2)


class TestSiIbisChannelTool:
    """Tests for the si_ibis_channel_response LLM tool."""

    async def _parse(self):
        r = await call(si_ibis_parse, ibs_text=SYNTHETIC_IBS)
        return next(m for m in r["models"] if m["name"] == "out_3v3")

    @pytest.mark.asyncio
    async def test_returns_waveform(self):
        model_dict = await self._parse()
        r = await call(
            si_ibis_channel_response,
            ibis_model_dict=model_dict,
            z0_ohms=50, length_mm=100, er=4.2, r_term_ohms=50,
        )
        assert "error" not in r
        assert "waveform_t_ns_V" in r
        assert len(r["waveform_t_ns_V"]) > 0

    @pytest.mark.asyncio
    async def test_td_ns_approx_half_ns_100mm_fr4(self):
        """TD for 100mm FR4 er=4.2 must be ~0.68 ns (within [0.4, 1.0] ns)."""
        model_dict = await self._parse()
        r = await call(
            si_ibis_channel_response,
            ibis_model_dict=model_dict,
            z0_ohms=50, length_mm=100, er=4.2, r_term_ohms=50,
        )
        assert 0.4 < r["td_ns"] < 1.0, f"TD={r['td_ns']:.3f} ns out of expected range"

    @pytest.mark.asyncio
    async def test_mismatch_waveform_higher_peak(self):
        """Z_term=200Ω should yield a higher peak than 50Ω (positive reflection)."""
        model_dict = await self._parse()
        r_match = await call(
            si_ibis_channel_response,
            ibis_model_dict=model_dict,
            z0_ohms=50, length_mm=100, er=4.2, r_term_ohms=50,
        )
        r_mismatch = await call(
            si_ibis_channel_response,
            ibis_model_dict=model_dict,
            z0_ohms=50, length_mm=100, er=4.2, r_term_ohms=200,
        )
        max_match = max(v for _, v in r_match["waveform_t_ns_V"])
        max_mismatch = max(v for _, v in r_mismatch["waveform_t_ns_V"])
        assert max_mismatch > max_match

    @pytest.mark.asyncio
    async def test_eye_diagram_returns_when_requested(self):
        model_dict = await self._parse()
        r = await call(
            si_ibis_channel_response,
            ibis_model_dict=model_dict,
            z0_ohms=50, length_mm=100, er=4.2, r_term_ohms=50,
            eye_diagram=True,
        )
        assert "eye_high_V" in r
        assert "eye_low_V" in r
        assert r["eye_high_V"] > r["eye_low_V"]

    @pytest.mark.asyncio
    async def test_missing_model_dict_returns_error(self):
        r = await call(si_ibis_channel_response)
        assert "error" in r

    @pytest.mark.asyncio
    async def test_bad_model_dict_type_returns_error(self):
        r = await call(si_ibis_channel_response, ibis_model_dict="not_a_dict")
        assert "error" in r


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sample_wave(wave, t_target):
    """Linear-interpolate a waveform at time t_target [s]."""
    for i in range(len(wave) - 1):
        t0, v0 = wave[i]
        t1, v1 = wave[i + 1]
        if t0 <= t_target <= t1:
            if t1 == t0:
                return v0
            frac = (t_target - t0) / (t1 - t0)
            return v0 + frac * (v1 - v0)
    return wave[-1][1]


def _time_to_v(wave, v_target):
    """Return first time the waveform crosses v_target."""
    for i in range(len(wave) - 1):
        t0, v0 = wave[i]
        t1, v1 = wave[i + 1]
        if v0 < v_target <= v1:
            frac = (v_target - v0) / (v1 - v0) if (v1 != v0) else 0.0
            return t0 + frac * (t1 - t0)
    return wave[-1][0]


# ── Teardown ─────────────────────────────────────────────────────────────────

def teardown_module(module):
    for _name, _orig in _KERF_CHAT_SAVED.items():
        if _orig is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _orig
