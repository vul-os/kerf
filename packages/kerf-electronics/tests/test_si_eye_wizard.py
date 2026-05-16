"""
Hermetic tests for the SI eye-diagram pre-compliance wizard (si_eye_wizard.py).

Coverage (≥25 tests):
  - Long lossy trace → closed/failing eye, negative margin reported
  - Recommended trace shortening re-runs model → eye opens & margin improves
  - Higher data rate → smaller eye (monotone)
  - Equalization recommendation → eye height improves in re-run
  - Matched Z0 → minimal reflection penalty vs mismatched
  - Pass case → compliant=True, margin positive, no critical fixes
  - Numbers consistent with calling si.solver + eye.model functions directly
  - Invalid inputs → ok=False, never raise
  - LLM tool wrapper (stub registry) — round-trips correctly

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Stub kerf_chat.tools.registry before any imports ─────────────────────────
try:
    import kerf_chat as _kc_pkg        # noqa: F401
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

_kc_stub = types.ModuleType("kerf_chat")
_kc_tools_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kc_stub)
sys.modules.setdefault("kerf_chat.tools", _kc_tools_stub)
if _kc_real is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ is on path ────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.si_eye_wizard import si_eye_precompliance
from kerf_electronics.eye.model import eye_estimate as _eye_estimate
from kerf_electronics.si.solver import (
    microstrip_z0,
    reflection_coefficient,
    propagation_delay_ps_per_mm,
)

# ── Load tool module via importlib (stub active) ──────────────────────────────
_wiz_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.si_eye_wizard",
    os.path.join(_SRC, "kerf_electronics", "si_eye_wizard.py"),
)
_wiz_mod = importlib.util.module_from_spec(_wiz_spec)
_wiz_spec.loader.exec_module(_wiz_mod)
_tool_fn = _wiz_mod.si_eye_precompliance_wizard


async def _call_tool(**kwargs) -> dict:
    raw = await _tool_fn(None, json.dumps(kwargs).encode())
    return json.loads(raw)


# ── Canonical channel fixtures ────────────────────────────────────────────────

# Long lossy trace (500 mm, 8 Gbps, FR4 flat loss 60 dB/m) → very closed eye
_LONG_LOSSY = {
    "data_rate_gbps": 8.0,
    "length_mm": 500.0,
    "loss_db_per_m": 60.0,   # 30 dB total IL → severely closed eye
    "rise_time_tx_ps": 30.0,
    "rj_ps": 2.0,
    "dj_ps": 10.0,
    "mask": "pcie_gen3",
}

# Short clean trace (50 mm, 2 Gbps, low loss) → open eye
_SHORT_CLEAN = {
    "data_rate_gbps": 2.0,
    "length_mm": 50.0,
    "loss_db_per_m": 10.0,   # 0.5 dB total IL → very open eye
    "rise_time_tx_ps": 50.0,
    "rj_ps": 0.5,
    "dj_ps": 2.0,
    "mask": "generic",
}

# Moderate channel — borderline, useful for equalization test
_MODERATE = {
    "data_rate_gbps": 5.0,
    "length_mm": 200.0,
    "skin_loss_db_per_sqrt_ghz": 5.0,
    "dielectric_loss_db_per_ghz": 3.0,
    "rise_time_tx_ps": 40.0,
    "rj_ps": 1.5,
    "dj_ps": 8.0,
    "mask": "usb3_gen1",
}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Basic structure
# ══════════════════════════════════════════════════════════════════════════════

class TestBasicStructure:
    def test_ok_keys_present(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert res["ok"] is True
        for k in ("compliant", "eye_height", "eye_width_ui",
                  "margin_height", "margin_width_ui", "mask_used",
                  "loss_db", "jitter", "checklist",
                  "findings", "recommendations", "summary"):
            assert k in res, f"missing key {k!r}"

    def test_jitter_keys_present(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        jitter = res["jitter"]
        for k in ("rj_ps", "dj_ps", "tj_ps", "tj_ui", "q_factor", "ber"):
            assert k in jitter, f"jitter missing key {k!r}"

    def test_checklist_keys_present(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        cl = res["checklist"]
        for k in ("z0_mismatch", "via_stub_resonance", "crosstalk_jitter"):
            assert k in cl, f"checklist missing key {k!r}"

    def test_recommendations_are_list(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert isinstance(res["recommendations"], list)

    def test_findings_are_list(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert isinstance(res["findings"], list)


# ══════════════════════════════════════════════════════════════════════════════
# 2. Long lossy trace → closed eye, negative margins
# ══════════════════════════════════════════════════════════════════════════════

class TestLongLossyTrace:
    def test_long_lossy_not_compliant(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        assert res["ok"] is True
        assert res["compliant"] is False

    def test_long_lossy_negative_height_margin(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        assert res["margin_height"] < 0, (
            f"Expected negative height margin, got {res['margin_height']}"
        )

    def test_long_lossy_eye_height_finding_reported(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        issues = [f["issue"] for f in res["findings"]]
        assert "eye_height_insufficient" in issues

    def test_long_lossy_loss_db_positive_large(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        # 500 mm × 60 dB/m = 30 dB
        assert abs(res["loss_db"] - 30.0) < 0.5

    def test_long_lossy_summary_says_fail(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        assert "FAIL" in res["summary"].upper() or "fail" in res["summary"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# 3. Trace-shortening recommendation: re-run shows eye opens & margin improves
# ══════════════════════════════════════════════════════════════════════════════

class TestShortTraceRecommendation:
    def test_shorten_trace_recommendation_present(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        actions = [r["action"] for r in res["recommendations"]]
        assert "shorten_trace" in actions

    def test_shorten_trace_after_eye_height_gt_before(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "shorten_trace")
        assert rec["after_eye_height"] > rec["before_eye_height"], (
            f"after={rec['after_eye_height']} must be > before={rec['before_eye_height']}"
        )

    def test_shorten_trace_after_margin_gt_before_margin(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "shorten_trace")
        assert rec["after_margin_height"] > rec["before_margin_height"]

    def test_shorten_trace_target_length_is_70_pct(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "shorten_trace")
        expected = _LONG_LOSSY["length_mm"] * 0.70
        assert abs(rec["target_length_mm"] - expected) < 0.1

    def test_shorten_trace_improvement_positive(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "shorten_trace")
        assert rec["improvement_eye_height"] > 0.0

    def test_shorten_trace_rerun_consistent_with_eye_model(self):
        """Wizard shortening result must match calling eye_estimate directly with reduced length."""
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "shorten_trace")

        short_len_mm = rec["target_length_mm"]
        short_len_inch = short_len_mm / 25.4
        # loss_db_per_inch at reduced length
        ldi = _LONG_LOSSY["loss_db_per_m"] / 1000.0 * 25.4  # dB/inch
        direct = _eye_estimate(
            loss_db_per_inch=ldi,
            length_inch=short_len_inch,
            bit_rate_bps=_LONG_LOSSY["data_rate_gbps"] * 1e9,
            rise_time_tx_s=_LONG_LOSSY["rise_time_tx_ps"] * 1e-12,
            isi_fraction=0.05,
            reflection_gamma=0.0,
        )
        assert direct["ok"]
        assert abs(rec["after_eye_height"] - direct["eye_height"]) < 1e-4


# ══════════════════════════════════════════════════════════════════════════════
# 4. Higher data rate → smaller eye (monotone)
# ══════════════════════════════════════════════════════════════════════════════

class TestDataRateMonotone:
    def test_higher_data_rate_smaller_eye_height(self):
        """Eye height is monotonically non-increasing with data rate."""
        base = {
            "length_mm": 150.0,
            "loss_db_per_m": 40.0,
            "rise_time_tx_ps": 30.0,
            "rj_ps": 1.0,
            "dj_ps": 5.0,
            "mask": "generic",
        }
        rates = [1.0, 2.0, 5.0, 8.0, 12.5, 25.0]
        eye_heights = []
        for dr in rates:
            ch = dict(base, data_rate_gbps=dr)
            res = si_eye_precompliance(ch)
            assert res["ok"], f"Failed at {dr} Gbps: {res.get('reason')}"
            eye_heights.append(res["eye_height"])

        # Eye height is non-increasing with data rate
        for i in range(1, len(eye_heights)):
            assert eye_heights[i] <= eye_heights[i - 1] + 1e-6, (
                f"Eye height increased from {rates[i-1]} Gbps to {rates[i]} Gbps: "
                f"{eye_heights[i-1]:.6f} → {eye_heights[i]:.6f}"
            )

    def test_higher_data_rate_smaller_eye_width(self):
        """Eye width (UI) is non-increasing with data rate for fixed ISI."""
        base = {
            "length_mm": 150.0,
            "loss_db_per_m": 40.0,
            "rise_time_tx_ps": 30.0,
            "rj_ps": 1.0,
            "dj_ps": 5.0,
            "mask": "generic",
        }
        rates = [2.0, 5.0, 10.0]
        widths = []
        for dr in rates:
            ch = dict(base, data_rate_gbps=dr)
            res = si_eye_precompliance(ch)
            assert res["ok"]
            widths.append(res["eye_width_ui"])

        for i in range(1, len(widths)):
            assert widths[i] <= widths[i - 1] + 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# 5. Equalization recommendation increases eye height in re-run
# ══════════════════════════════════════════════════════════════════════════════

class TestEqualization:
    def test_equalization_recommendation_present_when_failing(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        actions = [r["action"] for r in res["recommendations"]]
        assert "add_equalization" in actions

    def test_equalization_after_eye_height_gt_before(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "add_equalization")
        assert rec["after_eye_height"] > rec["before_eye_height"], (
            f"after={rec['after_eye_height']} must be > before={rec['before_eye_height']}"
        )

    def test_equalization_improvement_positive(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "add_equalization")
        assert rec["improvement_eye_height"] > 0.0

    def test_equalization_after_margin_better_than_before(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "add_equalization")
        assert rec["after_margin_height"] > rec["before_margin_height"]

    def test_equalization_gain_db_reported(self):
        res = si_eye_precompliance(_LONG_LOSSY)
        rec = next(r for r in res["recommendations"] if r["action"] == "add_equalization")
        assert "eq_gain_db" in rec
        assert rec["eq_gain_db"] > 0

    def test_equalization_with_skin_diel_model(self):
        """Equalization also works for skin+dielectric loss model."""
        res = si_eye_precompliance(_MODERATE)
        if not res["compliant"]:
            actions = [r["action"] for r in res["recommendations"]]
            assert "add_equalization" in actions
            rec = next(r for r in res["recommendations"] if r["action"] == "add_equalization")
            assert rec["after_eye_height"] > rec["before_eye_height"]


# ══════════════════════════════════════════════════════════════════════════════
# 6. Matched Z0 vs mismatched Z0 — reflection penalty
# ══════════════════════════════════════════════════════════════════════════════

class TestZ0Matching:
    def _make_z0_channel(self, gamma: float) -> dict:
        return {
            "data_rate_gbps": 5.0,
            "length_mm": 150.0,
            "loss_db_per_m": 30.0,
            "rise_time_tx_ps": 40.0,
            "reflection_gamma": gamma,
            "rj_ps": 1.0,
            "dj_ps": 5.0,
            "mask": "generic",
        }

    def test_matched_z0_higher_eye_height_than_mismatched(self):
        matched = si_eye_precompliance(self._make_z0_channel(gamma=0.0))
        mismatched = si_eye_precompliance(self._make_z0_channel(gamma=0.3))
        assert matched["ok"] and mismatched["ok"]
        assert matched["eye_height"] > mismatched["eye_height"]

    def test_zero_gamma_no_z0_mismatch_flag(self):
        res = si_eye_precompliance(self._make_z0_channel(gamma=0.0))
        assert not res["checklist"]["z0_mismatch"]["flagged"]

    def test_high_gamma_z0_mismatch_flagged(self):
        res = si_eye_precompliance(self._make_z0_channel(gamma=0.4))
        assert res["checklist"]["z0_mismatch"]["flagged"]

    def test_z0_mismatch_match_z0_recommendation_present(self):
        """When Z0 is mismatched and eye fails, match_z0 fix is recommended."""
        ch = self._make_z0_channel(gamma=0.5)
        # Force failure by using strict mask
        ch["mask"] = "pcie_gen3"
        ch["mask_height"] = 0.9  # very strict
        res = si_eye_precompliance(ch)
        if not res["compliant"]:
            actions = [r["action"] for r in res["recommendations"]]
            assert "match_z0" in actions

    def test_geometry_based_z0_computed(self):
        """When trace geometry supplied, z0_ohms appears in checklist."""
        ch = {
            "data_rate_gbps": 5.0,
            "length_mm": 100.0,
            "loss_db_per_m": 20.0,
            "trace_width_mm": 0.18,
            "dielectric_height_mm": 0.1,
            "er": 4.5,
            "copper_thickness_mm": 0.035,
            "z_load_ohms": 50.0,
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]
        z0_info = res["checklist"]["z0_mismatch"]
        assert z0_info["z0_ohms"] is not None
        assert z0_info["z0_ohms"] > 0

    def test_geometry_z0_consistent_with_solver(self):
        """Wizard-computed Z0 must match microstrip_z0 directly."""
        W, H, T, er = 0.18, 0.1, 0.035, 4.5
        ch = {
            "data_rate_gbps": 5.0,
            "length_mm": 100.0,
            "loss_db_per_m": 20.0,
            "trace_width_mm": W,
            "dielectric_height_mm": H,
            "er": er,
            "copper_thickness_mm": T,
            "z_load_ohms": 50.0,
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]
        direct_z0 = microstrip_z0(W, H, T, er)
        wizard_z0 = res["checklist"]["z0_mismatch"]["z0_ohms"]
        assert abs(wizard_z0 - direct_z0) < 0.1


# ══════════════════════════════════════════════════════════════════════════════
# 7. Pass case → compliant, margin positive, no height/width fix recommended
# ══════════════════════════════════════════════════════════════════════════════

class TestPassCase:
    def test_short_clean_compliant(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert res["ok"] is True
        assert res["compliant"] is True

    def test_pass_case_positive_height_margin(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert res["margin_height"] > 0, f"Expected positive margin, got {res['margin_height']}"

    def test_pass_case_positive_width_margin(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert res["margin_width_ui"] > 0

    def test_pass_case_no_shorten_recommendation(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        actions = [r["action"] for r in res["recommendations"]]
        assert "shorten_trace" not in actions

    def test_pass_case_no_height_insufficient_finding(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        issues = [f["issue"] for f in res["findings"]]
        assert "eye_height_insufficient" not in issues

    def test_pass_case_summary_says_compliant(self):
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert "compliant" in res["summary"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# 8. Numbers consistent with eye.model and si.solver directly
# ══════════════════════════════════════════════════════════════════════════════

class TestPhysicsConsistency:
    def test_loss_db_consistent_with_eye_model(self):
        """Wizard loss_db must match eye_estimate loss_db for flat IL model."""
        ch = {
            "data_rate_gbps": 8.0,
            "length_mm": 300.0,
            "loss_db_per_m": 40.0,
            "rise_time_tx_ps": 30.0,
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]
        # Expected IL: 300 mm × 40 dB/m / 1000 = 12 dB
        expected_il = 40.0 * 300.0 / 1000.0
        assert abs(res["loss_db"] - expected_il) < 0.01

    def test_eye_height_consistent_with_eye_model_direct(self):
        """Wizard eye_height must equal eye_estimate called with the same params."""
        ch = {
            "data_rate_gbps": 8.0,
            "length_mm": 300.0,
            "loss_db_per_m": 40.0,
            "rise_time_tx_ps": 30.0,
            "isi_fraction": 0.05,
            "reflection_gamma": 0.0,
            "rj_ps": 0.0,    # zero jitter so Tj/UI = 0
            "dj_ps": 0.0,
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]

        # Direct call to eye_estimate
        ldi = 40.0 / 1000.0 * 25.4   # dB/inch
        direct = _eye_estimate(
            loss_db_per_inch=ldi,
            length_inch=300.0 / 25.4,
            bit_rate_bps=8.0e9,
            rise_time_tx_s=30e-12,
            isi_fraction=0.05,
            reflection_gamma=0.0,
        )
        assert direct["ok"]
        assert abs(res["eye_height"] - direct["eye_height"]) < 1e-4

    def test_skin_diel_loss_model_additive(self):
        """Skin + dielectric coefficients add up correctly at Nyquist."""
        f_nyquist_ghz = 4.0  # 8 Gbps → fN = 4 GHz
        skin_c = 5.0   # dB / sqrt(GHz) / m
        diel_c = 3.0   # dB / GHz / m
        length_mm = 200.0
        expected_il = (skin_c * math.sqrt(f_nyquist_ghz) + diel_c * f_nyquist_ghz) * length_mm / 1000.0

        ch = {
            "data_rate_gbps": 8.0,
            "length_mm": length_mm,
            "skin_loss_db_per_sqrt_ghz": skin_c,
            "dielectric_loss_db_per_ghz": diel_c,
            "rise_time_tx_ps": 30.0,
            "rj_ps": 0.0,
            "dj_ps": 0.0,
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]
        assert abs(res["loss_db"] - expected_il) < 0.01

    def test_reflection_penalty_from_gamma_consistent(self):
        """Eye height reduction from gamma must match eye.model directly."""
        gamma = 0.25
        ch_base = {
            "data_rate_gbps": 5.0,
            "length_mm": 100.0,
            "loss_db_per_m": 20.0,
            "rise_time_tx_ps": 40.0,
            "isi_fraction": 0.05,
            "reflection_gamma": gamma,
            "rj_ps": 0.0,
            "dj_ps": 0.0,
            "mask": "generic",
        }
        res_with_gamma = si_eye_precompliance(ch_base)
        assert res_with_gamma["ok"]

        ldi = 20.0 / 1000.0 * 25.4
        direct = _eye_estimate(
            loss_db_per_inch=ldi,
            length_inch=100.0 / 25.4,
            bit_rate_bps=5.0e9,
            rise_time_tx_s=40e-12,
            isi_fraction=0.05,
            reflection_gamma=gamma,
        )
        assert direct["ok"]
        assert abs(res_with_gamma["eye_height"] - direct["eye_height"]) < 1e-4


# ══════════════════════════════════════════════════════════════════════════════
# 9. Via stub resonance pre-scan
# ══════════════════════════════════════════════════════════════════════════════

class TestViaStubResonance:
    def test_via_stub_resonance_flagged_near_nyquist(self):
        """A via stub tuned to near Nyquist should be flagged."""
        # For 10 Gbps: fN = 5 GHz
        # f_res = 0.2998 / (4 * L_mm * sqrt(4)) * 1000 = 37.47 / L_mm
        # So L_mm = 37.47 / 5 ≈ 7.5 mm puts resonance at ~5 GHz (within ±30%)
        ch = {
            "data_rate_gbps": 10.0,
            "length_mm": 100.0,
            "loss_db_per_m": 30.0,
            "via_stub_length_mm": 7.5,
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]
        assert res["checklist"]["via_stub_resonance"]["flagged"]

    def test_via_stub_not_flagged_far_from_nyquist(self):
        """A very short stub resonance far above Nyquist should not be flagged."""
        ch = {
            "data_rate_gbps": 5.0,
            "length_mm": 100.0,
            "loss_db_per_m": 20.0,
            "via_stub_length_mm": 1.0,   # resonance at ~75 GHz — far above 2.5 GHz Nyquist
            "mask": "generic",
        }
        res = si_eye_precompliance(ch)
        assert res["ok"]
        assert not res["checklist"]["via_stub_resonance"]["flagged"]

    def test_via_stub_no_stub_supplied(self):
        """Without via_stub_length_mm, resonance flag is False."""
        res = si_eye_precompliance(_SHORT_CLEAN)
        assert res["checklist"]["via_stub_resonance"]["flagged"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 10. Invalid inputs → ok=False, never raise
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidInputs:
    def test_not_a_dict(self):
        res = si_eye_precompliance("not a dict")
        assert res["ok"] is False
        assert "reason" in res

    def test_missing_data_rate(self):
        res = si_eye_precompliance({"length_mm": 100.0, "loss_db_per_m": 20.0})
        assert res["ok"] is False

    def test_missing_length(self):
        res = si_eye_precompliance({"data_rate_gbps": 5.0, "loss_db_per_m": 20.0})
        assert res["ok"] is False

    def test_missing_loss_parameter(self):
        res = si_eye_precompliance({"data_rate_gbps": 5.0, "length_mm": 100.0})
        assert res["ok"] is False
        assert "reason" in res

    def test_zero_data_rate(self):
        res = si_eye_precompliance({"data_rate_gbps": 0, "length_mm": 100.0, "loss_db_per_m": 20.0})
        assert res["ok"] is False

    def test_negative_length(self):
        res = si_eye_precompliance({"data_rate_gbps": 5.0, "length_mm": -10.0, "loss_db_per_m": 20.0})
        assert res["ok"] is False

    def test_negative_loss(self):
        res = si_eye_precompliance({"data_rate_gbps": 5.0, "length_mm": 100.0, "loss_db_per_m": -5.0})
        assert res["ok"] is False

    def test_negative_mask_height(self):
        res = si_eye_precompliance({
            "data_rate_gbps": 5.0, "length_mm": 100.0, "loss_db_per_m": 20.0,
            "mask_height": -0.1,
        })
        assert res["ok"] is False

    def test_never_raises_on_bad_inputs(self):
        """A range of bad inputs must return ok=False, never raise."""
        bad_inputs = [
            None,
            42,
            [],
            {},
            {"data_rate_gbps": -1, "length_mm": 100.0, "loss_db_per_m": 20.0},
            {"data_rate_gbps": 5.0, "length_mm": 0, "loss_db_per_m": 20.0},
            {"data_rate_gbps": 5.0, "length_mm": 100.0, "loss_db_per_m": 0},
            {"data_rate_gbps": float("nan"), "length_mm": 100.0, "loss_db_per_m": 20.0},
        ]
        for inp in bad_inputs:
            try:
                res = si_eye_precompliance(inp)
                assert res.get("ok") is False, f"Expected ok=False for {inp!r}"
            except Exception as exc:
                pytest.fail(f"si_eye_precompliance raised {exc!r} for input {inp!r}")


# ══════════════════════════════════════════════════════════════════════════════
# 11. LLM tool wrapper
# ══════════════════════════════════════════════════════════════════════════════

class TestToolWrapper:
    @pytest.mark.asyncio
    async def test_tool_ok_failing_channel(self):
        res = await _call_tool(**_LONG_LOSSY)
        assert res["ok"] is True
        assert res["compliant"] is False

    @pytest.mark.asyncio
    async def test_tool_ok_passing_channel(self):
        res = await _call_tool(**_SHORT_CLEAN)
        assert res["ok"] is True
        assert res["compliant"] is True

    @pytest.mark.asyncio
    async def test_tool_invalid_json(self):
        raw = await _tool_fn(None, b"{{not json")
        data = json.loads(raw)
        assert data.get("ok") is False or "error" in data

    @pytest.mark.asyncio
    async def test_tool_missing_loss_param(self):
        res = await _call_tool(data_rate_gbps=5.0, length_mm=100.0)
        assert res.get("ok") is False or "error" in res

    @pytest.mark.asyncio
    async def test_tool_roundtrip_eye_height(self):
        """Tool eye_height must match direct wizard call."""
        direct = si_eye_precompliance(_LONG_LOSSY)
        tool_res = await _call_tool(**_LONG_LOSSY)
        assert abs(tool_res["eye_height"] - direct["eye_height"]) < 1e-5

    @pytest.mark.asyncio
    async def test_tool_roundtrip_compliant_flag(self):
        direct = si_eye_precompliance(_SHORT_CLEAN)
        tool_res = await _call_tool(**_SHORT_CLEAN)
        assert tool_res["compliant"] == direct["compliant"]
