"""
Hermetic tests for the eye-diagram and jitter-budget estimator.

Strategy mirrors test_si.py:
  - Stub kerf_chat.tools.registry so the tool layer imports without the
    full kerf_chat stack.
  - Load the model (math) module directly from its file path.
  - Load the tool module from its file path.
  - All tests are self-contained; no network, no filesystem side-effects.

Author: imranparuk
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import types
import pytest

# ── Prefer real kerf_chat if available ───────────────────────────────────────
try:
    import kerf_chat as _kc_pkg          # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

# ── Stub kerf_chat.tools.registry ────────────────────────────────────────────
_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type("ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)})
_reg_stub.err_payload = lambda msg, code: json.dumps({"error": msg, "code": code})
_reg_stub.ok_payload = lambda v: json.dumps(v)
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kc_pkg_stub = types.ModuleType("kerf_chat")
_kc_tools_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kc_pkg_stub)
sys.modules.setdefault("kerf_chat.tools", _kc_tools_stub)
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Load model module ─────────────────────────────────────────────────────────
_model_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.eye.model",
    "packages/kerf-electronics/src/kerf_electronics/eye/model.py",
)
_model = importlib.util.module_from_spec(_model_spec)
_model_spec.loader.exec_module(_model)

eye_estimate_fn    = _model.eye_estimate
jitter_budget_fn   = _model.jitter_budget
eye_mask_check_fn  = _model.eye_mask_check
_q_factor          = _model._q_factor
_probit            = _model._probit

# ── Pre-register model sub-modules so the tool import resolves ───────────────
_ke_stub       = types.ModuleType("kerf_electronics")
_ke_eye_stub   = types.ModuleType("kerf_electronics.eye")
sys.modules.setdefault("kerf_electronics",     _ke_stub)
sys.modules.setdefault("kerf_electronics.eye", _ke_eye_stub)
sys.modules["kerf_electronics.eye.model"] = _model
# Bind the functions onto the stub package so `from kerf_electronics.eye.model import ...` works
_ke_eye_stub.eye_estimate  = eye_estimate_fn
_ke_eye_stub.jitter_budget = jitter_budget_fn
_ke_eye_stub.eye_mask_check = eye_mask_check_fn

# ── Load tool module ──────────────────────────────────────────────────────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.tools.eye",
    "packages/kerf-electronics/src/kerf_electronics/tools/eye.py",
)
_tool = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool)

eye_estimate_tool   = _tool.eye_estimate
jitter_budget_tool  = _tool.jitter_budget
eye_mask_check_tool = _tool.eye_mask_check


# ── Async helper ──────────────────────────────────────────────────────────────
async def call(fn, **kwargs):
    raw = await fn(None, json.dumps(kwargs).encode())
    return json.loads(raw)


# =============================================================================
# MODEL — eye_estimate
# =============================================================================

class TestEyeEstimateZeroLoss:
    """Zero-loss channel should produce a near-ideal eye."""

    def test_near_ideal_eye_height(self):
        r = eye_estimate_fn(
            loss_db_per_inch=0.001,   # near-zero loss
            length_inch=1.0,
            bit_rate_bps=1e9,
            rise_time_tx_s=100e-12,
            isi_fraction=0.0,
            reflection_gamma=0.0,
        )
        assert r["ok"]
        # attenuation ≈ 1, eye_height ≈ 2*1 = 2, minus zero penalty
        assert r["eye_height"] > 1.95, f"got {r['eye_height']}"

    def test_near_ideal_eye_width(self):
        r = eye_estimate_fn(
            loss_db_per_inch=0.001,
            length_inch=1.0,
            bit_rate_bps=1e9,
            rise_time_tx_s=10e-12,   # very fast tx
            isi_fraction=0.0,
            reflection_gamma=0.0,
        )
        assert r["ok"]
        # UI = 1 ns; rise_time_rx ≈ rise_time_tx (channel adds negligible); eye_width ≈ 1
        assert r["eye_width_ui"] > 0.85, f"got {r['eye_width_ui']}"

    def test_vec_near_zero(self):
        r = eye_estimate_fn(
            loss_db_per_inch=0.001,
            length_inch=1.0,
            bit_rate_bps=1e9,
            rise_time_tx_s=100e-12,
            isi_fraction=0.0,
            reflection_gamma=0.0,
        )
        assert r["ok"]
        assert r["vec"] < 0.05, f"VEC={r['vec']}"

    def test_attenuation_near_one(self):
        r = eye_estimate_fn(
            loss_db_per_inch=0.001,
            length_inch=1.0,
            bit_rate_bps=1e9,
            rise_time_tx_s=100e-12,
        )
        assert r["ok"]
        assert r["attenuation"] > 0.99


class TestEyeEstimateMonotone:
    """More loss → smaller eye height (monotone)."""

    def test_more_loss_smaller_height(self):
        r_low = eye_estimate_fn(0.2, 10.0, 5e9, 50e-12)
        r_high = eye_estimate_fn(0.8, 10.0, 5e9, 50e-12)
        assert r_low["ok"] and r_high["ok"]
        assert r_low["eye_height"] > r_high["eye_height"], (
            f"low_loss={r_low['eye_height']:.4f} high_loss={r_high['eye_height']:.4f}"
        )

    def test_more_loss_smaller_attenuation(self):
        r1 = eye_estimate_fn(0.3, 10.0, 10e9, 50e-12)
        r2 = eye_estimate_fn(0.6, 10.0, 10e9, 50e-12)
        assert r1["attenuation"] > r2["attenuation"]

    def test_longer_channel_smaller_height(self):
        r_short = eye_estimate_fn(0.5, 5.0,  5e9, 50e-12, isi_fraction=0.0, reflection_gamma=0.0)
        r_long  = eye_estimate_fn(0.5, 15.0, 5e9, 50e-12, isi_fraction=0.0, reflection_gamma=0.0)
        assert r_short["eye_height"] > r_long["eye_height"]

    def test_nonzero_isi_gives_positive_vec(self):
        # With ISI fraction > 0, VEC must be > 0 (eye is not ideal).
        r = eye_estimate_fn(0.3, 10.0, 5e9, 50e-12, isi_fraction=0.05)
        assert r["ok"]
        assert r["vec"] > 0.0, f"VEC should be > 0 when isi_fraction>0, got {r['vec']}"

    def test_vec_equals_isi_plus_gamma_ratio(self):
        # VEC = isi_fraction + |gamma| / 2  (derived from the formula when gamma*att/ideal = gamma/2)
        # Exact derivation: VEC = 1 - (ideal*(1-isi) - gamma*att)/ideal = isi + gamma*att/ideal
        # With isi=0, gamma=0: VEC=0; with isi=0.1, gamma=0: VEC=0.1
        r = eye_estimate_fn(0.3, 10.0, 5e9, 50e-12, isi_fraction=0.1, reflection_gamma=0.0)
        assert r["ok"]
        assert abs(r["vec"] - 0.1) < 1e-4, f"VEC={r['vec']}"

    def test_loss_db_matches_formula(self):
        r = eye_estimate_fn(0.5, 10.0, 5e9, 50e-12)
        assert r["ok"]
        assert abs(r["loss_db"] - 5.0) < 1e-6

    def test_attenuation_matches_formula(self):
        r = eye_estimate_fn(0.5, 10.0, 5e9, 50e-12)
        expected_att = 10 ** (-5.0 / 20.0)
        assert abs(r["attenuation"] - expected_att) < 1e-5


class TestEyeEstimateISIReflection:
    """ISI and reflection penalties reduce eye height."""

    def test_isi_reduces_height(self):
        r0 = eye_estimate_fn(0.3, 8.0, 5e9, 50e-12, isi_fraction=0.0)
        r1 = eye_estimate_fn(0.3, 8.0, 5e9, 50e-12, isi_fraction=0.1)
        assert r0["eye_height"] > r1["eye_height"]

    def test_reflection_reduces_height(self):
        r0 = eye_estimate_fn(0.3, 8.0, 5e9, 50e-12, reflection_gamma=0.0)
        r1 = eye_estimate_fn(0.3, 8.0, 5e9, 50e-12, reflection_gamma=0.2)
        assert r0["eye_height"] > r1["eye_height"]

    def test_large_isi_very_closed(self):
        r = eye_estimate_fn(0.5, 10.0, 5e9, 50e-12, isi_fraction=0.9)
        assert r["ok"]
        assert r["eye_height"] < r["details"]["eye_height_ideal"] * 0.15

    def test_gamma_1_completely_kills_eye(self):
        # gamma=1 means full reflection; eye_height = ideal - isi - att
        r = eye_estimate_fn(0.01, 1.0, 1e9, 100e-12, isi_fraction=0.0, reflection_gamma=1.0)
        assert r["ok"]
        # eye_height = 2*att - 0 - 1*att = att
        expected = r["attenuation"]
        assert abs(r["eye_height"] - expected) < 1e-5


class TestEyeEstimateInvalidInputs:
    """Invalid inputs return ok=False with a reason."""

    def test_negative_loss_returns_error(self):
        r = eye_estimate_fn(-0.5, 5.0, 5e9, 50e-12)
        assert not r["ok"]
        assert "loss_db_per_inch" in r["reason"]

    def test_zero_bit_rate_returns_error(self):
        r = eye_estimate_fn(0.5, 5.0, 0.0, 50e-12)
        assert not r["ok"]

    def test_zero_rise_time_returns_error(self):
        r = eye_estimate_fn(0.5, 5.0, 5e9, 0.0)
        assert not r["ok"]

    def test_isi_fraction_ge_1_returns_error(self):
        r = eye_estimate_fn(0.5, 5.0, 5e9, 50e-12, isi_fraction=1.0)
        assert not r["ok"]

    def test_gamma_gt_1_returns_error(self):
        r = eye_estimate_fn(0.5, 5.0, 5e9, 50e-12, reflection_gamma=1.1)
        assert not r["ok"]

    def test_none_loss_returns_error(self):
        r = eye_estimate_fn(None, 5.0, 5e9, 50e-12)
        assert not r["ok"]


# =============================================================================
# MODEL — jitter_budget
# =============================================================================

class TestJitterBudget:
    """Tests for Tj = Dj + 2*Rj*Q(BER)."""

    def test_basic_formula(self):
        # Q for BER=1e-12 should be ~7.034
        rj = 1e-12    # 1 ps
        dj = 5e-12    # 5 ps
        ber = 1e-12
        r = jitter_budget_fn(rj, dj, ber)
        assert r["ok"]
        # Use raw q (not rounded) to verify the formula holds
        q_raw = _q_factor(ber)
        expected_tj = dj + 2 * rj * q_raw
        # tj_s uses the full-precision q; tolerance accounts for floating point
        assert abs(r["tj_s"] - expected_tj) < 1e-18

    def test_q_factor_ber_1e12(self):
        # Q(1e-12) ≈ 7.034 (widely published value)
        r = jitter_budget_fn(1e-12, 0.0, 1e-12)
        assert r["ok"]
        assert 6.8 <= r["q"] <= 7.2, f"Q={r['q']:.4f}"

    def test_q_factor_ber_1e6(self):
        # Q(1e-6) ≈ 4.753
        r = jitter_budget_fn(1e-12, 0.0, 1e-6)
        assert r["ok"]
        assert 4.5 <= r["q"] <= 5.0, f"Q={r['q']:.4f}"

    def test_higher_ber_lower_q(self):
        # More relaxed BER → smaller Q → tighter (smaller) Tj
        r_tight = jitter_budget_fn(1e-12, 0.0, 1e-15)
        r_loose = jitter_budget_fn(1e-12, 0.0, 1e-6)
        assert r_tight["q"] > r_loose["q"], "tighter BER should give higher Q"

    def test_higher_ber_smaller_tj(self):
        r_tight = jitter_budget_fn(5e-12, 2e-12, 1e-15)
        r_loose  = jitter_budget_fn(5e-12, 2e-12, 1e-3)
        assert r_tight["tj_s"] > r_loose["tj_s"]

    def test_dj_zero(self):
        r = jitter_budget_fn(1e-12, 0.0, 1e-12)
        assert r["ok"]
        assert abs(r["dj_s"]) < 1e-20

    def test_rj_dominates_when_dj_zero(self):
        r = jitter_budget_fn(5e-12, 0.0, 1e-12)
        assert r["ok"]
        assert r["tj_s"] > r["rj_s"] * 2

    def test_formula_string_present(self):
        r = jitter_budget_fn(1e-12, 0.0, 1e-12)
        assert "formula" in r
        assert "Tj" in r["formula"]

    def test_invalid_rj_zero(self):
        r = jitter_budget_fn(0.0, 1e-12, 1e-12)
        assert not r["ok"]

    def test_invalid_ber_out_of_range(self):
        r = jitter_budget_fn(1e-12, 0.0, 0.6)
        assert not r["ok"]
        assert "ber" in r["reason"]

    def test_invalid_ber_zero(self):
        r = jitter_budget_fn(1e-12, 0.0, 0.0)
        assert not r["ok"]

    def test_dj_negative_returns_error(self):
        r = jitter_budget_fn(1e-12, -1e-12, 1e-12)
        assert not r["ok"]


# =============================================================================
# MODEL — eye_mask_check
# =============================================================================

class TestEyeMaskCheck:
    """Tests for pass/fail against a rectangular mask."""

    def _good_eye(self, height=1.5, width_ui=0.6):
        return {
            "ok": True,
            "eye_height": height,
            "eye_width_ui": width_ui,
        }

    def test_pass_when_margins_positive(self):
        r = eye_mask_check_fn(self._good_eye(1.5, 0.7), {"height": 1.0, "width_ui": 0.5})
        assert r["ok"]
        assert r["pass_"]
        assert r["margin_height"] > 0
        assert r["margin_width_ui"] > 0

    def test_fail_height_too_small(self):
        r = eye_mask_check_fn(self._good_eye(0.5, 0.7), {"height": 1.0, "width_ui": 0.3})
        assert r["ok"]
        assert not r["pass_"]
        assert r["margin_height"] < 0

    def test_fail_width_too_small(self):
        r = eye_mask_check_fn(self._good_eye(1.5, 0.2), {"height": 1.0, "width_ui": 0.5})
        assert r["ok"]
        assert not r["pass_"]
        assert r["margin_width_ui"] < 0

    def test_voffset_reduces_effective_height(self):
        # eye_height=1.5, voffset=0.3 → effective=1.2; mask height=1.1 → pass
        r = eye_mask_check_fn(
            self._good_eye(1.5, 0.7),
            {"height": 1.1, "width_ui": 0.5, "voffset": 0.3}
        )
        assert r["ok"]
        assert r["pass_"]
        # effective height = 1.5 - 0.3 = 1.2; margin = 1.2 - 1.1 = 0.1
        assert abs(r["margin_height"] - 0.1) < 1e-5

    def test_voffset_causes_fail(self):
        # eye_height=1.1, voffset=0.3 → effective=0.8; mask height=1.0 → fail
        r = eye_mask_check_fn(
            self._good_eye(1.1, 0.7),
            {"height": 1.0, "width_ui": 0.5, "voffset": 0.3}
        )
        assert r["ok"]
        assert not r["pass_"]

    def test_exact_margin_zero_passes(self):
        r = eye_mask_check_fn(self._good_eye(1.0, 0.5), {"height": 1.0, "width_ui": 0.5})
        assert r["ok"]
        assert r["pass_"]
        assert abs(r["margin_height"]) < 1e-9
        assert abs(r["margin_width_ui"]) < 1e-9

    def test_invalid_eye_no_ok_key(self):
        r = eye_mask_check_fn({"eye_height": 1.0, "eye_width_ui": 0.5}, {"height": 0.5, "width_ui": 0.3})
        assert not r["ok"]

    def test_missing_mask_height(self):
        r = eye_mask_check_fn(self._good_eye(), {"width_ui": 0.5})
        assert not r["ok"]

    def test_missing_mask_width(self):
        r = eye_mask_check_fn(self._good_eye(), {"height": 1.0})
        assert not r["ok"]


# =============================================================================
# INTEGRATION — real eye through mask
# =============================================================================

class TestEyePipeline:
    """End-to-end: eye_estimate → eye_mask_check."""

    def test_good_channel_passes_loose_mask(self):
        eye = eye_estimate_fn(0.2, 5.0, 5e9, 50e-12, isi_fraction=0.05)
        assert eye["ok"]
        r = eye_mask_check_fn(eye, {"height": 0.5, "width_ui": 0.2})
        assert r["ok"]
        assert r["pass_"]

    def test_bad_channel_fails_strict_mask(self):
        eye = eye_estimate_fn(1.0, 20.0, 25e9, 50e-12, isi_fraction=0.15)
        assert eye["ok"]
        r = eye_mask_check_fn(eye, {"height": 1.8, "width_ui": 0.7})
        assert r["ok"]
        assert not r["pass_"]


# =============================================================================
# TOOL LAYER — async JSON round-trips
# =============================================================================

class TestToolLayerEyeEstimate:
    """Verify tool wrappers return well-formed JSON."""

    @pytest.mark.asyncio
    async def test_basic_call_returns_ok(self):
        r = await call(eye_estimate_tool,
                       loss_db_per_inch=0.3, length_inch=10.0,
                       bit_rate_bps=5e9, rise_time_tx_s=50e-12)
        assert r.get("ok")
        assert "eye_height" in r
        assert "eye_width_ui" in r

    @pytest.mark.asyncio
    async def test_missing_required_returns_error(self):
        r = await call(eye_estimate_tool,
                       length_inch=10.0, bit_rate_bps=5e9, rise_time_tx_s=50e-12)
        assert "error" in r

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self):
        raw = await eye_estimate_tool(None, b"not-json{{{")
        r = json.loads(raw)
        assert "error" in r


class TestToolLayerJitterBudget:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        r = await call(jitter_budget_tool, rj_s=5e-12, dj_s=2e-12, ber=1e-12)
        assert r.get("ok")
        assert "tj_s" in r
        assert "q" in r

    @pytest.mark.asyncio
    async def test_missing_rj_returns_error(self):
        r = await call(jitter_budget_tool, dj_s=2e-12, ber=1e-12)
        assert "error" in r


class TestToolLayerEyeMaskCheck:
    @pytest.mark.asyncio
    async def test_pass_case(self):
        eye = {"ok": True, "eye_height": 1.5, "eye_width_ui": 0.7}
        r = await call(eye_mask_check_tool, eye=eye, mask={"height": 1.0, "width_ui": 0.5})
        assert r.get("ok")
        assert r.get("pass_")

    @pytest.mark.asyncio
    async def test_fail_case(self):
        eye = {"ok": True, "eye_height": 0.3, "eye_width_ui": 0.1}
        r = await call(eye_mask_check_tool, eye=eye, mask={"height": 1.0, "width_ui": 0.5})
        assert r.get("ok")
        assert not r.get("pass_")

    @pytest.mark.asyncio
    async def test_missing_eye_returns_error(self):
        r = await call(eye_mask_check_tool, mask={"height": 1.0, "width_ui": 0.5})
        assert "error" in r
