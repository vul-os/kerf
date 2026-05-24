"""
Tests for PDN AC impedance analysis (ac_impedance.py).

Coverage:
  - Component impedance models (VRM, bulk cap, MLCC, plane)
  - Via and spreading inductance estimators
  - Network solver: admittance sum, parallel combination
  - Analytic MLCC validation: fSR within 1%, |Z| at fSR = ESR
  - Target-impedance check: Z_target formula, violating bands, margins
  - Decap bank optimiser: greedy convergence, meets_target
  - LLM tool wrappers round-trip

All pure-Python — no numpy required.

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Stub kerf_chat if not installed (mirrors test_pdn_wizard.py pattern) ──────
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

# ── Ensure src/ on sys.path ───────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.pdn.ac_impedance import (
    PDNComponent,
    TargetZResult,
    vrm_impedance,
    bulk_cap_impedance,
    mlcc_impedance,
    plane_impedance,
    via_inductance_h,
    spreading_inductance_h,
    pdn_impedance_sweep,
    target_z_check,
    recommend_decap_bank,
    validate_single_mlcc,
    _srf_hz,
    _TWO_PI,
    _Z_OPEN,
)

# ── Load tool module for LLM wrapper tests ────────────────────────────────────
_ac_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.pdn.ac_impedance",
    os.path.join(_SRC, "kerf_electronics", "pdn", "ac_impedance.py"),
)
_ac_mod = importlib.util.module_from_spec(_ac_spec)
_ac_spec.loader.exec_module(_ac_mod)
_sweep_tool = _ac_mod.pdn_ac_impedance_sweep_tool
_recommend_tool = _ac_mod.pdn_recommend_decaps_tool


async def _call_sweep(**kwargs) -> dict:
    raw = await _sweep_tool(None, json.dumps(kwargs).encode())
    return json.loads(raw)


async def _call_recommend(**kwargs) -> dict:
    raw = await _recommend_tool(None, json.dumps(kwargs).encode())
    return json.loads(raw)


# ── Constants ─────────────────────────────────────────────────────────────────
# Analytic test case: 10 µF MLCC, ESR=5 mΩ, ESL=1 nH
_C = 10e-6
_ESR = 5e-3
_ESL = 1e-9
_F_SR_ANALYTIC = 1.0 / (_TWO_PI * math.sqrt(_ESL * _C))   # ≈ 1.592 MHz


# =============================================================================
# 1. Analytic MLCC validation — spec requirement: fSR within 1%, |Z|=ESR at fSR
# =============================================================================

class TestAnalyticMLCCValidation:
    """Primary spec validation: single MLCC 10µF/5mΩ/1nH."""

    def test_fsr_analytic_value(self):
        """f_sr ≈ 1.59 MHz for 10µF / 1nH."""
        assert abs(_F_SR_ANALYTIC - 1.592e6) / 1.592e6 < 0.01

    def test_solver_fsr_within_1pct(self):
        """Solver must find f_sr within 1% of analytic value."""
        result = validate_single_mlcc(c=_C, r_esr=_ESR, l_esl=_ESL)
        assert result["pass"], (
            f"fSR error {result['fsr_error_frac']*100:.3f}% exceeds 1% limit; "
            f"analytic={result['analytic_fsr_hz']/1e6:.4f} MHz, "
            f"solver={result['solver_fsr_hz']/1e6:.4f} MHz"
        )
        assert result["fsr_error_frac"] < 0.01

    def test_z_at_fsr_equals_esr(self):
        """At f_sr, |Z| must equal R_esr (reactive parts cancel)."""
        result = validate_single_mlcc(c=_C, r_esr=_ESR, l_esl=_ESL)
        # Allow 2% tolerance (grid resolution artefact)
        assert result["z_error_frac"] < 0.02, (
            f"|Z| at fSR: got {result['solver_z_at_fsr']*1e3:.4f} mΩ, "
            f"expected {_ESR*1e3:.1f} mΩ"
        )

    def test_validate_returns_expected_keys(self):
        result = validate_single_mlcc()
        for key in (
            "analytic_fsr_hz", "solver_fsr_hz", "fsr_error_frac",
            "analytic_z_at_fsr", "solver_z_at_fsr", "z_error_frac", "pass",
        ):
            assert key in result, f"missing key: {key!r}"


# =============================================================================
# 2. VRM impedance model
# =============================================================================

class TestVRMImpedance:
    def test_dc_equals_r_out(self):
        """At ω→0 (below bandwidth) VRM impedance is R_out."""
        z = vrm_impedance(1e-3, r_out=5e-3, l_out=10e-9, bw_rad_per_s=1e9)
        # At very low ω, jωL is negligible
        assert abs(z.real - 5e-3) < 1e-6

    def test_above_bw_is_open(self):
        """Above loop bandwidth, VRM returns Z_OPEN."""
        bw = _TWO_PI * 1e6  # 1 MHz
        omega_above = bw * 10.0
        z = vrm_impedance(omega_above, r_out=5e-3, l_out=10e-9, bw_rad_per_s=bw)
        assert abs(z) >= abs(_Z_OPEN) * 0.99

    def test_default_bw_is_rl_corner(self):
        """Default bw = R/L; just below that frequency VRM is not open."""
        r_out, l_out = 10e-3, 100e-9
        bw_default = r_out / l_out  # rad/s
        omega_below = bw_default * 0.5
        z = vrm_impedance(omega_below, r_out=r_out, l_out=l_out)
        assert abs(z) < abs(_Z_OPEN) / 2.0

    def test_impedance_rises_with_frequency(self):
        """Below bandwidth, VRM |Z| increases with ω (inductive)."""
        z1 = vrm_impedance(1e3, r_out=5e-3, l_out=10e-9, bw_rad_per_s=1e12)
        z2 = vrm_impedance(1e6, r_out=5e-3, l_out=10e-9, bw_rad_per_s=1e12)
        assert abs(z2) > abs(z1)


# =============================================================================
# 3. Bulk cap / MLCC impedance
# =============================================================================

class TestCapImpedance:
    def test_bulk_cap_srf_minimum(self):
        """Bulk cap |Z| minimum occurs at self-resonant frequency."""
        c, r_esr, l_esl = 100e-6, 20e-3, 20e-9
        f_sr = _srf_hz(c, l_esl)
        omega_sr = _TWO_PI * f_sr
        z_sr = bulk_cap_impedance(omega_sr, c, r_esr, l_esl)
        # |Z| at SRF ≈ ESR
        assert abs(abs(z_sr) - r_esr) / r_esr < 0.001

    def test_bulk_cap_capacitive_below_srf(self):
        """Well below SRF: |Z| ≈ 1/(ω·C)."""
        c, r_esr, l_esl = 100e-6, 20e-3, 20e-9
        f_sr = _srf_hz(c, l_esl)
        f = f_sr * 0.01
        omega = _TWO_PI * f
        z = bulk_cap_impedance(omega, c, r_esr, l_esl)
        z_cap = 1.0 / (omega * c)
        assert abs(abs(z) - z_cap) / z_cap < 0.01

    def test_bulk_cap_inductive_above_srf(self):
        """Well above SRF: |Z| ≈ ω·L_esl."""
        c, r_esr, l_esl = 100e-6, 20e-3, 20e-9
        f_sr = _srf_hz(c, l_esl)
        f = f_sr * 100.0
        omega = _TWO_PI * f
        z = bulk_cap_impedance(omega, c, r_esr, l_esl)
        z_ind = omega * l_esl
        assert abs(abs(z) - z_ind) / z_ind < 0.01

    def test_mlcc_mount_inductance_lowers_srf(self):
        """Adding mount inductance increases L_total, lowers SRF."""
        c, r_esr, l_esl, l_mount = 1e-6, 2e-3, 0.5e-9, 0.3e-9
        srf_no_mount = _srf_hz(c, l_esl)
        srf_with_mount = _srf_hz(c, l_esl + l_mount)
        assert srf_with_mount < srf_no_mount

    def test_mlcc_impedance_at_srf(self):
        """MLCC |Z| at SRF = ESR (mount inductance included)."""
        c, r_esr, l_esl, l_mount = 10e-6, 5e-3, 1e-9, 0.0
        f_sr = _srf_hz(c, l_esl + l_mount)
        omega_sr = _TWO_PI * f_sr
        z = mlcc_impedance(omega_sr, c, r_esr, l_esl, l_mount)
        assert abs(abs(z) - r_esr) / r_esr < 0.001


# =============================================================================
# 4. Plane impedance
# =============================================================================

class TestPlaneImpedance:
    def test_plane_capacitive_at_low_freq(self):
        """At low frequency the plane is dominated by C_plane."""
        z_lo = plane_impedance(1e3, side_m=0.1, height_m=100e-6)
        z_hi = plane_impedance(1e6, side_m=0.1, height_m=100e-6)
        # |Z| should drop with frequency in capacitive regime
        assert abs(z_lo) > abs(z_hi)

    def test_plane_impedance_finite_at_1mhz(self):
        """Plane impedance at 1 MHz must be finite and positive."""
        z = plane_impedance(_TWO_PI * 1e6, side_m=0.05, height_m=200e-6)
        assert abs(z) > 0.0
        assert abs(z) < 1e6  # not open

    def test_thinner_dielectric_larger_capacitance(self):
        """Halving dielectric thickness doubles C_plane and halves |Z| at low freq."""
        f_lo = 1e3
        z1 = plane_impedance(f_lo, side_m=0.1, height_m=200e-6)
        z2 = plane_impedance(f_lo, side_m=0.1, height_m=100e-6)
        # Thinner = more C = lower |Z|
        assert abs(z2) < abs(z1)


# =============================================================================
# 5. Parasitic inductance estimators
# =============================================================================

class TestParasiticEstimators:
    def test_via_inductance_positive(self):
        """Via inductance must be positive."""
        l = via_inductance_h(length_m=1e-3, radius_m=100e-6)
        assert l > 0.0

    def test_via_inductance_scales_with_length(self):
        """Longer via → more inductance."""
        l1 = via_inductance_h(length_m=0.5e-3, radius_m=100e-6)
        l2 = via_inductance_h(length_m=1.0e-3, radius_m=100e-6)
        assert l2 > l1

    def test_via_inductance_typical_range(self):
        """1 mm via at 100 µm radius should be ~0.5–2 nH."""
        l = via_inductance_h(length_m=1e-3, radius_m=100e-6)
        assert 0.3e-9 < l < 3e-9

    def test_via_invalid_zero_length(self):
        with pytest.raises(ValueError):
            via_inductance_h(0.0, 100e-6)

    def test_spreading_inductance_positive(self):
        l = spreading_inductance_h(side_m=0.1, height_m=100e-6)
        assert l > 0.0

    def test_spreading_inductance_typical_range(self):
        """100x100mm plane, 100µm dielectric: L = µ0*h/(2a) ≈ 0.63 nH."""
        l = spreading_inductance_h(side_m=0.1, height_m=100e-6)
        # µ0 * 100e-6 / (2 * 0.1) = 4π×10⁻⁷ * 100e-6 / 0.2 ≈ 6.3×10⁻¹⁰ H
        assert 0.1e-9 < l < 5e-9


# =============================================================================
# 6. Network solver
# =============================================================================

class TestNetworkSolver:
    def test_single_component_passthrough(self):
        """Single component: Z_pdn = Z_component."""
        comp = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9)
        freqs = [1e3, 1e6, 1e9]
        z_vals = pdn_impedance_sweep([comp], freqs)
        for f, z in zip(freqs, z_vals):
            omega = _TWO_PI * f
            z_direct = mlcc_impedance(omega, 10e-6, 5e-3, 1e-9)
            assert abs(z - z_direct) / max(abs(z_direct), 1e-15) < 1e-9

    def test_two_identical_caps_half_impedance(self):
        """Two identical caps in parallel halve the impedance vs one."""
        freqs = [1e4, 1e5]  # well below SRF, capacitive
        comp1 = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9, count=1)
        comp2 = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9, count=2)
        z1 = pdn_impedance_sweep([comp1], freqs)
        z2 = pdn_impedance_sweep([comp2], freqs)
        for a, b in zip(z1, z2):
            assert abs(abs(b) - abs(a) / 2.0) / abs(a) < 0.01

    def test_empty_components_returns_open(self):
        z = pdn_impedance_sweep([], [1e6])
        assert abs(z[0]) >= abs(_Z_OPEN) * 0.99

    def test_vrm_plus_cap_lower_than_vrm_alone(self):
        """Adding a cap in parallel always lowers |Z|."""
        freqs = [1e6]
        vrm = PDNComponent(kind="vrm", r_out=5e-3, l_out=10e-9, bw_hz=1e8)
        cap = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9)
        z_vrm = pdn_impedance_sweep([vrm], freqs)
        z_both = pdn_impedance_sweep([vrm, cap], freqs)
        assert abs(z_both[0]) < abs(z_vrm[0])

    def test_admittance_sum_for_three_caps(self):
        """Three different caps: Y_total = sum of individual admittances."""
        f = 5e5
        omega = _TWO_PI * f
        specs = [
            (10e-6, 5e-3, 1e-9, 1),
            (100e-9, 30e-3, 1e-9, 2),
            (10e-9, 50e-3, 0.5e-9, 4),
        ]
        comps = [
            PDNComponent(kind="mlcc", c=c, r_esr=r, l_esl=l, count=n)
            for c, r, l, n in specs
        ]
        z_solver = pdn_impedance_sweep(comps, [f])[0]
        # Manual admittance sum
        y_manual = sum(
            n / mlcc_impedance(omega, c, r, l)
            for c, r, l, n in specs
        )
        z_manual = 1.0 / y_manual
        assert abs(z_solver - z_manual) / abs(z_manual) < 1e-9


# =============================================================================
# 7. Target-impedance check
# =============================================================================

class TestTargetZCheck:
    def test_z_target_formula(self):
        """Z_target = V * ripple_pct/100 / I."""
        z_vals = [complex(1e-3, 0)] * 3
        freqs = [1e3, 1e6, 1e9]
        result = target_z_check(z_vals, freqs, v_supply=3.3, i_max=10.0, ripple_pct=5.0)
        expected = 3.3 * 0.05 / 10.0
        assert abs(result.z_target_ohm - expected) < 1e-12

    def test_meets_target_when_z_below(self):
        """If all |Z| < Z_target, meets_target=True, no violating bands."""
        z_target = 0.1
        z_vals = [complex(0.05, 0)] * 5
        freqs = [1e3, 1e4, 1e5, 1e6, 1e7]
        # Scale so z_target formula gives 0.1: V=1, ripple=10%, I=1
        result = target_z_check(z_vals, freqs, v_supply=1.0, i_max=1.0, ripple_pct=10.0)
        assert result.meets_target is True
        assert len(result.violating_bands) == 0

    def test_violating_band_detected(self):
        """If |Z| > Z_target at some frequencies, bands are flagged."""
        freqs = [1e3, 1e4, 1e5, 1e6, 1e7]
        z_target_calc = 1.0 * 0.05 / 1.0  # = 0.05 Ω
        z_vals = [
            complex(0.02, 0),   # below
            complex(0.1, 0),    # above  ← band start
            complex(0.2, 0),    # above
            complex(0.08, 0),   # above
            complex(0.01, 0),   # below  ← band end
        ]
        result = target_z_check(z_vals, freqs, v_supply=1.0, i_max=1.0, ripple_pct=5.0)
        assert result.meets_target is False
        assert len(result.violating_bands) >= 1
        band = result.violating_bands[0]
        assert band["z_peak_ohm"] >= 0.1

    def test_margin_db_positive_when_z_below_target(self):
        """Margin > 0 dB when |Z| < Z_target."""
        result = target_z_check(
            [complex(0.01, 0)], [1e6], v_supply=1.0, i_max=1.0, ripple_pct=5.0
        )
        assert result.margin_db[0] > 0.0

    def test_worst_peak_correct(self):
        """worst_peak_ohm is the maximum |Z| across all frequencies."""
        z_vals = [complex(0.01, 0), complex(0.5, 0), complex(0.2, 0)]
        result = target_z_check(z_vals, [1e3, 1e6, 1e9], 1.0, 1.0, 5.0)
        assert abs(result.worst_peak_ohm - 0.5) < 1e-12
        assert abs(result.worst_peak_hz - 1e6) < 1.0


# =============================================================================
# 8. Decap bank optimiser
# =============================================================================

class TestDecapOptimiser:
    def _mlcc_caps(self):
        """Small catalogue of MLCCs at different values."""
        return [
            {"c": 100e-6, "r_esr": 10e-3, "l_esl": 10e-9, "cost_each": 0.10, "name": "100uF"},
            {"c": 10e-6,  "r_esr": 5e-3,  "l_esl": 1e-9,  "cost_each": 0.05, "name": "10uF"},
            {"c": 100e-9, "r_esr": 30e-3, "l_esl": 1e-9,  "cost_each": 0.02, "name": "100nF"},
            {"c": 10e-9,  "r_esr": 50e-3, "l_esl": 0.5e-9,"cost_each": 0.01, "name": "10nF"},
        ]

    def test_returns_required_keys(self):
        freqs = [10 ** x for x in range(3, 9)]
        result = recommend_decap_bank(freqs, 0.1, self._mlcc_caps())
        for k in ("recommended", "total_cost", "meets_target", "iterations"):
            assert k in result

    def test_empty_caps_returns_gracefully(self):
        freqs = [1e6]
        result = recommend_decap_bank(freqs, 0.05, [])
        assert result["meets_target"] is False

    def test_recommended_counts_nonnegative(self):
        freqs = [10 ** x for x in range(4, 9)]
        result = recommend_decap_bank(freqs, 0.05, self._mlcc_caps())
        for r in result["recommended"]:
            assert r["count"] > 0

    def test_total_cost_matches_sum(self):
        freqs = [10 ** x for x in range(4, 9)]
        result = recommend_decap_bank(freqs, 0.05, self._mlcc_caps())
        expected_total = sum(r["count"] * r["cost_each"] for r in result["recommended"])
        assert abs(result["total_cost"] - expected_total) < 1e-9

    def test_optimiser_adds_caps_when_needed(self):
        """With a very tight target, optimiser should add multiple caps."""
        freqs = [10 ** x for x in range(3, 9)]
        result = recommend_decap_bank(freqs, 1e-3, self._mlcc_caps())
        total_count = sum(r["count"] for r in result["recommended"])
        assert total_count > 0

    def test_looser_target_needs_fewer_caps(self):
        """Looser target → fewer or equal caps vs tight target."""
        freqs = [10 ** x for x in range(4, 9)]
        res_tight = recommend_decap_bank(freqs, 0.001, self._mlcc_caps())
        res_loose = recommend_decap_bank(freqs, 0.5, self._mlcc_caps())
        tight_count = sum(r["count"] for r in res_tight["recommended"])
        loose_count = sum(r["count"] for r in res_loose["recommended"])
        assert loose_count <= tight_count


# =============================================================================
# 9. PDNComponent dataclass helpers
# =============================================================================

class TestPDNComponent:
    def test_mlcc_srf_hz(self):
        comp = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9, l_mount=0.0)
        srf = comp.srf_hz()
        assert srf is not None
        expected = 1.0 / (_TWO_PI * math.sqrt(1e-9 * 10e-6))
        assert abs(srf - expected) / expected < 1e-9

    def test_vrm_has_no_srf(self):
        comp = PDNComponent(kind="vrm", r_out=5e-3, l_out=10e-9)
        assert comp.srf_hz() is None

    def test_parallel_impedance_count_1(self):
        comp = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9, count=1)
        omega = _TWO_PI * 1e5
        assert comp.parallel_impedance(omega) == comp.impedance(omega)

    def test_parallel_impedance_count_4(self):
        """4 caps in parallel: Z_parallel = Z_single / 4."""
        comp1 = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9, count=1)
        comp4 = PDNComponent(kind="mlcc", c=10e-6, r_esr=5e-3, l_esl=1e-9, count=4)
        omega = _TWO_PI * 1e5
        z1 = comp1.parallel_impedance(omega)
        z4 = comp4.parallel_impedance(omega)
        assert abs(z4 - z1 / 4.0) / abs(z1) < 1e-9

    def test_unknown_kind_raises(self):
        comp = PDNComponent(kind="unknown_xyz")
        with pytest.raises(ValueError):
            comp.impedance(1e6)


# =============================================================================
# 10. LLM tool wrappers
# =============================================================================

class TestToolWrappers:
    @pytest.mark.asyncio
    async def test_sweep_tool_ok(self):
        res = await _call_sweep(
            v_supply=3.3, i_max=10.0, ripple_pct=5.0,
            mlccs=[{"c": 10e-6, "r_esr": 5e-3, "l_esl": 1e-9}],
        )
        assert res["ok"] is True
        assert "z_target_ohm" in res
        assert abs(res["z_target_ohm"] - 3.3 * 0.05 / 10.0) < 1e-12

    @pytest.mark.asyncio
    async def test_sweep_tool_invalid_json(self):
        raw = await _sweep_tool(None, b"not json{{")
        data = json.loads(raw)
        # Error payload: either {"ok": False, ...} or {"error": ..., "code": ...}
        assert data.get("ok") is False or "error" in data

    @pytest.mark.asyncio
    async def test_sweep_tool_no_components(self):
        res = await _call_sweep(v_supply=3.3, i_max=10.0, ripple_pct=5.0)
        assert res.get("ok") is False or "error" in res

    @pytest.mark.asyncio
    async def test_sweep_tool_with_vrm_and_plane(self):
        res = await _call_sweep(
            v_supply=1.8, i_max=5.0, ripple_pct=3.0,
            vrm={"r_out": 5e-3, "l_out": 10e-9, "bw_hz": 1e7},
            mlccs=[
                {"c": 100e-6, "r_esr": 10e-3, "l_esl": 10e-9, "count": 2},
                {"c": 10e-6, "r_esr": 5e-3, "l_esl": 1e-9, "count": 5},
            ],
            plane={"side_m": 0.05, "height_m": 200e-6},
        )
        assert res["ok"] is True
        assert "z_mag_ohm" in res
        assert len(res["z_mag_ohm"]) == len(res["freqs_hz"])

    @pytest.mark.asyncio
    async def test_sweep_tool_z_target_formula(self):
        """Tool must return correct z_target."""
        res = await _call_sweep(
            v_supply=5.0, i_max=2.0, ripple_pct=10.0,
            mlccs=[{"c": 100e-6, "r_esr": 10e-3, "l_esl": 10e-9}],
        )
        assert res["ok"] is True
        assert abs(res["z_target_ohm"] - 5.0 * 0.10 / 2.0) < 1e-12

    @pytest.mark.asyncio
    async def test_recommend_tool_ok(self):
        res = await _call_recommend(
            v_supply=3.3, i_max=5.0, ripple_pct=5.0,
            available_caps=[
                {"c": 10e-6, "r_esr": 5e-3, "l_esl": 1e-9, "cost_each": 0.05},
                {"c": 100e-9, "r_esr": 30e-3, "l_esl": 1e-9, "cost_each": 0.02},
            ],
        )
        assert res["ok"] is True
        assert "recommended" in res
        assert "z_target_ohm" in res

    @pytest.mark.asyncio
    async def test_recommend_tool_invalid_json(self):
        raw = await _recommend_tool(None, b"{{{bad")
        data = json.loads(raw)
        assert data.get("ok") is False or "error" in data

    @pytest.mark.asyncio
    async def test_recommend_tool_zero_current(self):
        res = await _call_recommend(
            v_supply=3.3, i_max=0.0, ripple_pct=5.0,
            available_caps=[{"c": 10e-6, "r_esr": 5e-3, "l_esl": 1e-9}],
        )
        assert res.get("ok") is False or "error" in res


# ── Teardown ──────────────────────────────────────────────────────────────────

def teardown_module(module):
    for name, orig in _KERF_CHAT_SAVED.items():
        if orig is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = orig
