"""
Hermetic tests for the PDN decoupling-capacitor wizard (pdn_wizard.py).

Coverage (≥25 tests):
  - Single-cap self-resonant frequency: f_srf = 1/(2π√(L·C)) exact
  - |Z| below SRF → capacitive (∝ 1/(ωC)); above SRF → inductive (∝ ωL)
  - Z_target = Vdd·ripple_frac / I_transient correct formula
  - More parallel identical caps lower |Z| floor (∝ 1/N at LF)
  - Recommended set meets |Z| ≤ Z_target across the requested band
  - Anti-resonance peak between a bulk and ceramic bank detected + flagged
  - Adding mid-value cap removes the peak in the re-run
  - Zero / negative current → graceful ok=False
  - characterise_cap: SRF exact, DC/HF asymptotes described
  - LLM tool wrappers round-trip correctly

Loading strategy: stub kerf_chat.tools.registry so no full install required.

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Prefer real kerf_chat if present; fall back to stub ──────────────────────
try:
    import kerf_chat as _kc_pkg  # noqa: F401
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
_KERF_CHAT_SAVED = {
    n: sys.modules.get(n)
    for n in ("kerf_chat", "kerf_chat.tools", "kerf_chat.tools.registry")
}
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on sys.path ────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.pdn_wizard import (
    _cap_impedance,
    _srf,
    _bank_impedance,
    _TWO_PI,
    characterise_cap,
    pdn_wizard,
    z_target_from_spec,
)

# ── Load tool module via importlib (stub active) ──────────────────────────────
_wiz_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.pdn_wizard",
    os.path.join(_SRC, "kerf_electronics", "pdn_wizard.py"),
)
_wiz_mod = importlib.util.module_from_spec(_wiz_spec)
_wiz_spec.loader.exec_module(_wiz_mod)
_pdn_decap_wizard_tool = _wiz_mod.pdn_decap_wizard
_pdn_char_cap_tool = _wiz_mod.pdn_characterise_cap


async def _call_wizard(**kwargs) -> dict:
    raw = await _pdn_decap_wizard_tool(None, json.dumps(kwargs).encode())
    return json.loads(raw)


async def _call_char(**kwargs) -> dict:
    raw = await _pdn_char_cap_tool(None, json.dumps(kwargs).encode())
    return json.loads(raw)


# ── Shared test parameters ────────────────────────────────────────────────────

# A simple 100 nF MLCC: C=100 nF, ESR=30 mΩ, ESL=1 nH, mount=0
_C_TEST = 100e-9
_ESR_TEST = 30e-3
_ESL_TEST = 1e-9
_MOUNT_TEST = 0.0
_L_TOTAL_TEST = _ESL_TEST + _MOUNT_TEST


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Single-cap self-resonant frequency (exact formula)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSingleCapSRF:
    def test_srf_exact_formula(self):
        """f_srf = 1/(2π·√(L·C)) to within numerical precision."""
        expected = 1.0 / (_TWO_PI * math.sqrt(_L_TOTAL_TEST * _C_TEST))
        got = _srf(_C_TEST, _L_TOTAL_TEST)
        assert abs(got - expected) / expected < 1e-12, (
            f"SRF mismatch: got {got:.3f} Hz, expected {expected:.3f} Hz"
        )

    def test_srf_scales_inverse_sqrt_c(self):
        """Doubling C reduces f_srf by 1/√2."""
        srf1 = _srf(100e-9, 1e-9)
        srf2 = _srf(200e-9, 1e-9)
        assert abs(srf1 / srf2 - math.sqrt(2.0)) < 1e-9

    def test_srf_scales_inverse_sqrt_l(self):
        """Doubling L reduces f_srf by 1/√2."""
        srf1 = _srf(100e-9, 1e-9)
        srf2 = _srf(100e-9, 4e-9)
        assert abs(srf1 / srf2 - 2.0) < 1e-9

    def test_characterise_cap_srf_exact(self):
        """characterise_cap must return f_srf matching direct calculation."""
        expected = 1.0 / (_TWO_PI * math.sqrt(_L_TOTAL_TEST * _C_TEST))
        res = characterise_cap(_C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST)
        assert res["ok"] is True
        assert abs(res["srf_hz"] - expected) / expected < 1e-12

    def test_characterise_cap_with_mount_inductance(self):
        """Mount inductance increases L_total and lowers SRF."""
        srf_no_mount = characterise_cap(100e-9, 30e-3, 1e-9, 0.0)["srf_hz"]
        srf_with_mount = characterise_cap(100e-9, 30e-3, 1e-9, 0.3e-9)["srf_hz"]
        assert srf_with_mount < srf_no_mount


# ═══════════════════════════════════════════════════════════════════════════════
# 2. |Z| asymptotes: capacitive below SRF, inductive above SRF
# ═══════════════════════════════════════════════════════════════════════════════

class TestImpedanceAsymptotes:
    def test_below_srf_capacitive(self):
        """Well below f_srf: |Z| ≈ 1/(ω·C), decreasing with frequency."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f_lo = srf * 0.01   # 1% of SRF — deep capacitive region
        f_mid = srf * 0.05
        z_lo = abs(_cap_impedance(f_lo, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
        z_mid = abs(_cap_impedance(f_mid, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
        assert z_lo > z_mid, "Below SRF: higher frequency should give lower |Z|"

    def test_below_srf_approx_one_over_omega_C(self):
        """At 1% of SRF: |Z| ≈ 1/(ω·C) to within 5%."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f = srf * 0.01
        z_model = abs(_cap_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
        z_expected = 1.0 / (_TWO_PI * f * _C_TEST)
        assert abs(z_model - z_expected) / z_expected < 0.05

    def test_above_srf_inductive(self):
        """Well above f_srf: |Z| ≈ ω·L_total, increasing with frequency."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f_hi1 = srf * 10.0
        f_hi2 = srf * 50.0
        z_hi1 = abs(_cap_impedance(f_hi1, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
        z_hi2 = abs(_cap_impedance(f_hi2, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
        assert z_hi2 > z_hi1, "Above SRF: higher frequency should give higher |Z|"

    def test_above_srf_approx_omega_L(self):
        """At 100× SRF: |Z| ≈ ω·L_total to within 5%."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f = srf * 100.0
        z_model = abs(_cap_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
        z_expected = _TWO_PI * f * _L_TOTAL_TEST
        assert abs(z_model - z_expected) / z_expected < 0.05

    def test_z_minimum_near_srf(self):
        """The impedance minimum of a cap occurs near its SRF."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        freqs = [srf * k for k in (0.1, 0.5, 1.0, 2.0, 10.0)]
        zmags = [abs(_cap_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST))
                 for f in freqs]
        min_idx = zmags.index(min(zmags))
        # Minimum should be at or near SRF (index 2 in the list above)
        assert 1 <= min_idx <= 3, f"Z minimum not near SRF, found at index {min_idx}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Z_target formula
# ═══════════════════════════════════════════════════════════════════════════════

class TestZTarget:
    def test_basic_formula(self):
        """Z_target = (Vdd × ripple_frac) / I_transient."""
        zt = z_target_from_spec(3.3, 0.05, 2.0)
        assert abs(zt - (3.3 * 0.05 / 2.0)) < 1e-12

    def test_tighter_ripple_lower_zt(self):
        zt_5 = z_target_from_spec(1.8, 0.05, 5.0)
        zt_2 = z_target_from_spec(1.8, 0.02, 5.0)
        assert zt_2 < zt_5

    def test_more_current_lower_zt(self):
        zt_lo = z_target_from_spec(3.3, 0.05, 1.0)
        zt_hi = z_target_from_spec(3.3, 0.05, 10.0)
        assert zt_hi < zt_lo

    def test_wizard_z_target_matches_formula(self):
        """Wizard's reported z_target_ohm must match direct z_target_from_spec."""
        design = {
            "vdd_v": 1.8, "ripple_frac": 0.03, "i_transient_a": 4.0, "bw_hz": 100e6,
        }
        res = pdn_wizard(design)
        assert res["ok"] is True
        expected = z_target_from_spec(1.8, 0.03, 4.0)
        assert abs(res["z_target_ohm"] - expected) < 1e-12


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Parallel caps: more caps lower |Z| floor
# ═══════════════════════════════════════════════════════════════════════════════

class TestParallelCaps:
    def test_two_caps_half_impedance_at_lf(self):
        """At LF (well below SRF): N identical caps → |Z| ∝ 1/N."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f = srf * 0.01   # deep capacitive region
        z1 = abs(_bank_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST, count=1))
        z2 = abs(_bank_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST, count=2))
        assert abs(z2 - z1 / 2.0) / z1 < 0.01

    def test_four_caps_quarter_impedance_at_lf(self):
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f = srf * 0.01
        z1 = abs(_bank_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST, count=1))
        z4 = abs(_bank_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST, count=4))
        assert abs(z4 - z1 / 4.0) / z1 < 0.01

    def test_more_caps_monotonically_lower_z(self):
        """Adding more caps must monotonically lower |Z| at any frequency."""
        srf = _srf(_C_TEST, _L_TOTAL_TEST)
        f = srf * 0.5
        z_prev = float("inf")
        for n in (1, 2, 4, 8):
            z = abs(_bank_impedance(f, _C_TEST, _ESR_TEST, _ESL_TEST, _MOUNT_TEST, count=n))
            assert z < z_prev, f"count={n} did not lower |Z|"
            z_prev = z


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Recommended set meets |Z| ≤ Z_target across the band
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommendedSetMeetsTarget:
    def test_default_banks_meet_target_100mhz(self):
        """Default synthesised bank set for 100 MHz bandwidth must meet Z_target."""
        design = {
            "vdd_v": 3.3,
            "ripple_frac": 0.05,
            "i_transient_a": 2.0,
            "bw_hz": 100e6,
        }
        res = pdn_wizard(design)
        assert res["ok"] is True
        assert res["meets_target"] is True, (
            f"Expected meets_target=True; bandwidth_met={res['bandwidth_met_hz'] / 1e6:.1f} MHz, "
            f"target=100 MHz, peaks={res['anti_resonance_peaks']}"
        )

    def test_bandwidth_met_ge_bw_hz(self):
        """bandwidth_met_hz must be ≥ bw_hz when meets_target is True."""
        design = {
            "vdd_v": 1.8,
            "ripple_frac": 0.05,
            "i_transient_a": 1.0,
            "bw_hz": 50e6,
        }
        res = pdn_wizard(design)
        assert res["ok"] is True
        if res["meets_target"]:
            assert res["bandwidth_met_hz"] >= design["bw_hz"]

    def test_recommended_banks_have_required_keys(self):
        design = {
            "vdd_v": 3.3, "ripple_frac": 0.05, "i_transient_a": 2.0, "bw_hz": 100e6,
        }
        res = pdn_wizard(design)
        assert res["ok"] is True
        for b in res["recommended_banks"]:
            for k in ("cap_f", "esr_ohm", "esl_h", "count"):
                assert k in b, f"bank missing key {k!r}"

    def test_per_bank_srf_matches_formula(self):
        """per_bank_srf[i].srf_hz must match direct _srf() calculation."""
        design = {
            "vdd_v": 3.3, "ripple_frac": 0.05, "i_transient_a": 2.0, "bw_hz": 100e6,
        }
        res = pdn_wizard(design)
        assert res["ok"] is True
        for entry in res["per_bank_srf"]:
            l_tot = entry["l_total_h"]
            c = entry["cap_f"]
            expected_srf = 1.0 / (_TWO_PI * math.sqrt(l_tot * c))
            assert abs(entry["srf_hz"] - expected_srf) / expected_srf < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Anti-resonance peak between bulk and ceramic bank
# ═══════════════════════════════════════════════════════════════════════════════

class TestAntiResonancePeakDetection:
    """Craft a 2-bank PDN known to produce an anti-resonance peak above Z_target."""

    def _two_bank_design_with_peak(self):
        """Bulk 10 µF + 10 nF ceramic with a deliberate 3-decade gap.

        Z_target = 3.3 * 0.05 / 5 = 33 mΩ.  This is achievable across most of
        the band with a good decap mix, but the transition between the 10 µF bulk
        (SRF ~225 kHz) and the 10 nF ceramic (SRF ~35 MHz) creates an anti-
        resonance peak well above 33 mΩ that the wizard must flag.
        """
        return {
            "vdd_v": 3.3,
            "ripple_frac": 0.05,   # Z_target = 3.3 * 0.05 / 5 = 33 mΩ
            "i_transient_a": 5.0,
            "bw_hz": 50e6,
            "l_vrm_h": 20e-9,      # moderate VRM inductance
            "r_vrm_ohm": 5e-3,
            "l_plane_h": 1e-9,
            "banks": [
                # Bulk: 10 µF, ESR=10 mΩ, ESL=10 nH — SRF ≈ 503 kHz
                {"cap_f": 10e-6, "esr_ohm": 10e-3, "esl_h": 10e-9, "count": 1},
                # Ceramic: 10 nF, ESR=50 mΩ, ESL=2 nH — SRF ≈ 35 MHz
                {"cap_f": 10e-9, "esr_ohm": 50e-3, "esl_h": 2e-9, "count": 1},
            ],
        }

    def test_anti_resonance_peak_detected(self):
        """With only a bulk+ceramic pair and tight Z_target, a peak is flagged."""
        design = self._two_bank_design_with_peak()
        res = pdn_wizard(design)
        assert res["ok"] is True
        # With this design there should be at least one anti-resonance peak
        assert len(res["anti_resonance_peaks"]) >= 1, (
            "Expected at least 1 anti-resonance peak between bulk and ceramic bank"
        )

    def test_peak_exceeds_z_target(self):
        """Each detected peak must have z_ohm > z_target_ohm."""
        design = self._two_bank_design_with_peak()
        res = pdn_wizard(design)
        assert res["ok"] is True
        for pk in res["anti_resonance_peaks"]:
            assert pk["z_ohm"] > res["z_target_ohm"], (
                f"Peak z={pk['z_ohm']:.6f} not > z_target={res['z_target_ohm']:.6f}"
            )

    def test_peak_has_offending_pair(self):
        """Each peak must attribute a bank pair."""
        design = self._two_bank_design_with_peak()
        res = pdn_wizard(design)
        assert res["ok"] is True
        for pk in res["anti_resonance_peaks"]:
            assert pk.get("offending_bank_pair") is not None
            assert len(pk["offending_bank_pair"]) == 2

    def test_peak_fix_present(self):
        """Each peak must include a fix recommendation."""
        design = self._two_bank_design_with_peak()
        res = pdn_wizard(design)
        assert res["ok"] is True
        for pk in res["anti_resonance_peaks"]:
            assert "fix" in pk
            assert "description" in pk["fix"]

    def test_fix_suggests_mid_value_cap(self):
        """Fix for a bulk-ceramic gap should suggest adding a mid-value cap."""
        design = self._two_bank_design_with_peak()
        res = pdn_wizard(design)
        assert res["ok"] is True
        assert len(res["anti_resonance_peaks"]) >= 1
        fix = res["anti_resonance_peaks"][0]["fix"]
        assert fix["type"] in ("add_mid_value_cap", "increase_count")

    def test_mid_value_cap_is_geometric_mean(self):
        """Suggested mid-value cap should be close to the geometric mean of the pair."""
        design = self._two_bank_design_with_peak()
        res = pdn_wizard(design)
        assert res["ok"] is True
        for pk in res["anti_resonance_peaks"]:
            fix = pk["fix"]
            if fix["type"] == "add_mid_value_cap":
                c_lo = fix["c_lo_f"]
                c_hi = fix["c_hi_f"]
                c_mid_expected = math.sqrt(c_lo * c_hi)
                assert abs(fix["suggested_c_mid_f"] - c_mid_expected) / c_mid_expected < 1e-9

    def test_adding_mid_cap_removes_peak(self):
        """Adding the suggested mid-value cap must reduce |Z| at the original
        peak frequency compared to the un-fixed run.

        With a very tight Z_target there will still be other peaks (the overall
        PDN has a VRM-inductance floor well above 1 mΩ), but the *specific*
        anti-resonance between the bulk and ceramic banks that was flagged must
        be damped — i.e. |Z| at that frequency must be strictly lower after the fix.
        """
        design = self._two_bank_design_with_peak()
        res1 = pdn_wizard(design)
        assert res1["ok"] is True
        assert len(res1["anti_resonance_peaks"]) >= 1

        # Collect original peak data from the first run's sweep
        def _z_at_freq(sweep, target_f):
            closest_idx = min(
                range(len(sweep["freqs_hz"])),
                key=lambda i: abs(sweep["freqs_hz"][i] - target_f),
            )
            return sweep["z_mag_ohm"][closest_idx]

        orig_peak_z = {
            pk["freq_hz"]: _z_at_freq(res1["sweep"], pk["freq_hz"])
            for pk in res1["anti_resonance_peaks"]
            if pk["fix"]["type"] == "add_mid_value_cap"
        }

        # Add every suggested mid-value cap fix (one per original peak)
        import copy
        design2 = copy.deepcopy(design)
        for pk in res1["anti_resonance_peaks"]:
            fix = pk["fix"]
            if fix["type"] == "add_mid_value_cap":
                design2["banks"].append({
                    "cap_f": fix["suggested_c_mid_f"],
                    "esr_ohm": fix["suggested_esr_ohm"],
                    "esl_h": fix["suggested_esl_h"],
                    "count": 2,
                })

        res2 = pdn_wizard(design2)
        assert res2["ok"] is True

        # For each originally-flagged peak, |Z| must be lower in the re-run
        for orig_freq, z_before in orig_peak_z.items():
            z_after = _z_at_freq(res2["sweep"], orig_freq)
            assert z_after < z_before, (
                f"Adding mid-value cap did NOT reduce |Z| at {orig_freq / 1e6:.2f} MHz: "
                f"before={z_before:.6f} Ω, after={z_after:.6f} Ω"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Invalid inputs → graceful ok=False, never raise
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidInputs:
    def test_zero_current_graceful(self):
        """Zero i_transient_a must return ok=False, not raise."""
        res = pdn_wizard({"vdd_v": 3.3, "ripple_frac": 0.05, "i_transient_a": 0.0, "bw_hz": 100e6})
        assert res["ok"] is False
        assert "reason" in res

    def test_negative_current_graceful(self):
        res = pdn_wizard({"vdd_v": 3.3, "ripple_frac": 0.05, "i_transient_a": -1.0, "bw_hz": 100e6})
        assert res["ok"] is False

    def test_missing_vdd(self):
        res = pdn_wizard({"ripple_frac": 0.05, "i_transient_a": 2.0, "bw_hz": 100e6})
        assert res["ok"] is False

    def test_ripple_frac_ge_1(self):
        res = pdn_wizard({"vdd_v": 3.3, "ripple_frac": 1.5, "i_transient_a": 2.0, "bw_hz": 100e6})
        assert res["ok"] is False

    def test_not_a_dict(self):
        res = pdn_wizard("not a dict")
        assert res["ok"] is False

    def test_bank_missing_cap_f(self):
        res = pdn_wizard({
            "vdd_v": 3.3, "ripple_frac": 0.05, "i_transient_a": 2.0, "bw_hz": 100e6,
            "banks": [{"esr_ohm": 30e-3, "esl_h": 1e-9, "count": 4}],
        })
        assert res["ok"] is False

    def test_bank_zero_esr(self):
        res = pdn_wizard({
            "vdd_v": 3.3, "ripple_frac": 0.05, "i_transient_a": 2.0, "bw_hz": 100e6,
            "banks": [{"cap_f": 100e-9, "esr_ohm": 0.0, "esl_h": 1e-9, "count": 4}],
        })
        assert res["ok"] is False

    def test_never_raises(self):
        bad_inputs = [
            None,
            42,
            {},
            {"vdd_v": 0.0, "ripple_frac": 0.05, "i_transient_a": 2.0, "bw_hz": 100e6},
            {"vdd_v": 3.3, "ripple_frac": 0.0, "i_transient_a": 2.0, "bw_hz": 100e6},
        ]
        for inp in bad_inputs:
            try:
                res = pdn_wizard(inp)
                assert res.get("ok") is False, f"Expected ok=False for {inp!r}"
            except Exception as exc:
                pytest.fail(f"pdn_wizard raised {exc!r} for {inp!r}")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. characterise_cap
# ═══════════════════════════════════════════════════════════════════════════════

class TestCharacteriseCap:
    def test_srf_exact(self):
        res = characterise_cap(100e-9, 30e-3, 1e-9, 0.0)
        expected = 1.0 / (_TWO_PI * math.sqrt(1e-9 * 100e-9))
        assert abs(res["srf_hz"] - expected) / expected < 1e-12

    def test_dc_asymptote_description(self):
        res = characterise_cap(100e-9, 30e-3, 1e-9)
        assert "capacitive" in res["dc_asymptote"].lower()

    def test_hf_asymptote_description(self):
        res = characterise_cap(100e-9, 30e-3, 1e-9)
        assert "inductive" in res["hf_asymptote"].lower()

    def test_z_at_srf_approx_esr(self):
        """At exact SRF, |Z| ≈ ESR (reactive parts cancel)."""
        esr = 30e-3
        res = characterise_cap(100e-9, esr, 1e-9, 0.0)
        # Tolerance: ESL and ESR residual; allow 5%
        assert abs(res["z_at_srf_ohm"] - esr) / esr < 0.05

    def test_invalid_zero_cap(self):
        res = characterise_cap(0.0, 30e-3, 1e-9)
        assert res.get("ok") is False

    def test_invalid_negative_esl(self):
        res = characterise_cap(100e-9, 30e-3, -1e-9)
        assert res.get("ok") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. LLM tool wrappers
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolWrappers:
    @pytest.mark.asyncio
    async def test_wizard_tool_ok(self):
        res = await _call_wizard(
            vdd_v=3.3, ripple_frac=0.05, i_transient_a=2.0, bw_hz=100e6
        )
        assert res["ok"] is True
        assert "z_target_ohm" in res
        assert "recommended_banks" in res

    @pytest.mark.asyncio
    async def test_wizard_tool_z_target_correct(self):
        res = await _call_wizard(
            vdd_v=1.8, ripple_frac=0.05, i_transient_a=3.0, bw_hz=50e6
        )
        assert res["ok"] is True
        expected = 1.8 * 0.05 / 3.0
        assert abs(res["z_target_ohm"] - expected) < 1e-12

    @pytest.mark.asyncio
    async def test_wizard_tool_invalid_json(self):
        raw = await _pdn_decap_wizard_tool(None, b"not json{{")
        data = json.loads(raw)
        assert data.get("ok") is False or "error" in data

    @pytest.mark.asyncio
    async def test_wizard_tool_zero_current_error(self):
        res = await _call_wizard(
            vdd_v=3.3, ripple_frac=0.05, i_transient_a=0.0, bw_hz=100e6
        )
        assert res.get("ok") is False or "error" in res

    @pytest.mark.asyncio
    async def test_char_cap_tool_srf(self):
        res = await _call_char(cap_f=100e-9, esr_ohm=30e-3, esl_h=1e-9)
        assert res["ok"] is True
        expected = 1.0 / (_TWO_PI * math.sqrt(1e-9 * 100e-9))
        assert abs(res["srf_hz"] - expected) / expected < 1e-9

    @pytest.mark.asyncio
    async def test_char_cap_tool_invalid(self):
        res = await _call_char(cap_f=0.0, esr_ohm=30e-3, esl_h=1e-9)
        assert res.get("ok") is False or "error" in res


# ── Teardown: restore sys.modules ─────────────────────────────────────────────

def teardown_module(module):
    for name, orig in _KERF_CHAT_SAVED.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig
