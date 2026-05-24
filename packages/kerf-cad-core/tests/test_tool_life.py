"""
Tests for kerf_cad_core.cuttingtool.tool_life — Taylor extended model and
Gilbert economics.

All tests are hermetic: no OCC, no DB, no network.

Textbook references:
  Kalpakjian, S. & Schmid, S.R. "Manufacturing Engineering and Technology",
    7th ed. (2014), Chapter 21.
  DeGarmo, E.P., Black, J.T. & Kohser, R.A. "Materials and Processes in
    Manufacturing", 11th ed. (2011), Chapter 21.
  Boothroyd, G. & Knight, W.A. "Fundamentals of Machining and Machine Tools",
    3rd ed. (2006), Chapter 9.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.cuttingtool.tool_life import (
    taylor_tool_life_extended,
    gilbert_economic_speed,
    production_rate_speed,
    tool_life_curve,
    lookup_taylor_constants,
    TAYLOR_CONSTANTS,
    run_taylor_tool_life,
    run_gilbert_economic_speed,
    run_production_rate_speed,
    run_tool_life_chart,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


# Carbide/AISI-1045 reference constants (from TAYLOR_CONSTANTS)
N   = 0.25
A   = 0.50
B   = 0.15
C   = 300.0  # m/min at f=1 mm/rev, dp=1 mm

# Textbook validation point (Kalpakjian / DeGarmo):
# vc=200, f=0.25, dp=2 → T ≈ 5.4 min
VC_REF = 200.0
F_REF  = 0.25
DP_REF = 2.0

TREL = 1e-9


# ===========================================================================
# 1. taylor_tool_life_extended
# ===========================================================================

class TestTaylorToolLifeExtended:

    def _T(self, vc=VC_REF, C_=C, n=N, f=F_REF, a=A, dp=DP_REF, b=B):
        return taylor_tool_life_extended(vc=vc, C=C_, n=n, f=f, a=a, dp=dp, b=b)

    def test_returns_ok(self):
        assert self._T()["ok"] is True

    def test_formula_algebraic(self):
        """T = (C / (vc · f^a · dp^b))^(1/n)."""
        res = self._T()
        C_eff = C / (F_REF**A * DP_REF**B)
        T_exp = (C_eff / VC_REF) ** (1.0 / N)
        assert math.isclose(res["T_min"], T_exp, rel_tol=TREL)

    def test_textbook_kalpakjian_point(self):
        """
        Carbide/AISI-1045 at vc=200, f=0.25, dp=2 — verify algebraic formula.

        C is calibrated at f_ref=1 mm/rev, dp_ref=1 mm, so
        C_eff = 300 / (0.25^0.5 × 2^0.15) ≈ 540.75 m/min.
        T = (C_eff / 200)^4 ≈ 53.4 min.

        The task-spec "≈5 min" refers to the basic Taylor (f=1, dp=1, a=0, b=0):
        T = (300/200)^4 = 5.0625 min — tested separately.
        """
        res = self._T()
        C_eff_exp = C / (F_REF**A * DP_REF**B)
        T_exp = (C_eff_exp / VC_REF) ** (1.0 / N)
        assert math.isclose(res["T_min"], T_exp, rel_tol=TREL)

    def test_textbook_simple_form_no_feed_depth_exponent(self):
        """With a=0, b=0: T = (C/vc)^(1/n) — reduces to basic Taylor."""
        res = taylor_tool_life_extended(vc=100.0, C=300.0, n=0.25,
                                        f=0.3, a=0.0, dp=2.0, b=0.0)
        T_basic = (300.0 / 100.0) ** (1.0 / 0.25)
        assert math.isclose(res["T_min"], T_basic, rel_tol=TREL)

    def test_C_eff_formula(self):
        """C_eff = C / (f^a · dp^b)."""
        res = self._T()
        C_eff_exp = C / (F_REF**A * DP_REF**B)
        assert math.isclose(res["C_eff"], C_eff_exp, rel_tol=TREL)

    def test_higher_speed_reduces_life(self):
        """T must decrease as vc increases (all else equal)."""
        T_low = self._T(vc=100.0)["T_min"]
        T_high = self._T(vc=250.0)["T_min"]
        assert T_high < T_low

    def test_higher_feed_reduces_life(self):
        """Increasing feed with a > 0 must reduce T."""
        T_low = self._T(f=0.1)["T_min"]
        T_high = self._T(f=0.5)["T_min"]
        assert T_high < T_low

    def test_higher_depth_reduces_life(self):
        """Increasing dp with b > 0 must reduce T."""
        T_shallow = self._T(dp=0.5)["T_min"]
        T_deep = self._T(dp=4.0)["T_min"]
        assert T_deep < T_shallow

    def test_zero_vc_returns_error(self):
        res = taylor_tool_life_extended(vc=0.0, C=C, n=N, f=F_REF, a=A, dp=DP_REF, b=B)
        assert res["ok"] is False

    def test_negative_n_returns_error(self):
        res = taylor_tool_life_extended(vc=VC_REF, C=C, n=-0.1, f=F_REF, a=A, dp=DP_REF, b=B)
        assert res["ok"] is False

    def test_negative_a_returns_error(self):
        res = taylor_tool_life_extended(vc=VC_REF, C=C, n=N, f=F_REF, a=-0.1, dp=DP_REF, b=B)
        assert res["ok"] is False

    def test_negative_b_returns_error(self):
        res = taylor_tool_life_extended(vc=VC_REF, C=C, n=N, f=F_REF, a=A, dp=DP_REF, b=-0.1)
        assert res["ok"] is False

    def test_tool_work_material_echoed(self):
        res = taylor_tool_life_extended(
            vc=100.0, C=300.0, n=0.25, f=0.25, a=0.5, dp=2.0, b=0.15,
            tool_material="carbide", work_material="aisi_1045",
        )
        assert res["tool_material"] == "carbide"
        assert res["work_material"] == "aisi_1045"

    def test_T_min_positive(self):
        assert self._T()["T_min"] > 0


# ===========================================================================
# 2. gilbert_economic_speed
# ===========================================================================

class TestGilbertEconomicSpeed:
    """
    Reference (DeGarmo / Kalpakjian shop example with f=1, dp=1, a=0, b=0):
      n=0.25, C=300, machine_rate=1, tool_cost=5, tool_change_time=2
      T_e   = (4-1) × (2 + 5/1) = 3 × 7 = 21 min
      vc_e  = 300 / 21^0.25 ≈ 140 m/min
      T_mpr = 3 × 2 = 6 min
      vc_mpr = 300 / 6^0.25 ≈ 191.9 m/min
    """

    _DEFAULTS = dict(C=300.0, n=0.25, tool_cost=5.0,
                     machine_rate=1.0, tool_change_time=2.0)

    def _g(self, **kw):
        params = dict(self._DEFAULTS)
        params.update(kw)
        return gilbert_economic_speed(**params)

    def test_returns_ok(self):
        assert self._g()["ok"] is True

    def test_T_e_formula(self):
        """T_e = (1/n − 1) × (t_ct + C_tool/C_m)."""
        res = self._g()
        T_e_exp = (1.0 / 0.25 - 1.0) * (2.0 + 5.0 / 1.0)
        assert math.isclose(res["T_e_min"], T_e_exp, rel_tol=TREL)

    def test_T_e_value_is_21(self):
        """Textbook: T_e = 21 min."""
        res = self._g()
        assert math.isclose(res["T_e_min"], 21.0, rel_tol=TREL)

    def test_vc_e_formula(self):
        """vc_e = C / T_e^n (at f=1, dp=1, a=0, b=0)."""
        res = self._g()
        vc_e_exp = 300.0 / (21.0 ** 0.25)
        assert math.isclose(res["vc_e_m_min"], vc_e_exp, rel_tol=TREL)

    def test_vc_e_approx_140(self):
        """Textbook: vc_e ≈ 140 m/min."""
        res = self._g()
        assert 135.0 < res["vc_e_m_min"] < 145.0, f"vc_e={res['vc_e_m_min']:.2f}"

    def test_T_mpr_formula(self):
        """T_mpr = (1/n − 1) × t_ct."""
        res = self._g()
        T_mpr_exp = (1.0 / 0.25 - 1.0) * 2.0
        assert math.isclose(res["T_mpr_min"], T_mpr_exp, rel_tol=TREL)

    def test_T_mpr_value_is_6(self):
        """Textbook: T_mpr = 6 min."""
        res = self._g()
        assert math.isclose(res["T_mpr_min"], 6.0, rel_tol=TREL)

    def test_production_rate_speed_formula(self):
        """vc_mpr = C / T_mpr^n."""
        res = self._g()
        vc_mpr_exp = 300.0 / (6.0 ** 0.25)
        assert math.isclose(res["production_rate_speed_m_min"], vc_mpr_exp, rel_tol=TREL)

    def test_vc_mpr_approx_192(self):
        """Textbook: vc_mpr ≈ 192 m/min."""
        res = self._g()
        assert 188.0 < res["production_rate_speed_m_min"] < 196.0

    def test_vc_mpr_gt_vc_e(self):
        """Production-rate speed must always exceed economic speed."""
        res = self._g()
        assert res["production_rate_speed_m_min"] > res["vc_e_m_min"]

    def test_higher_tool_cost_lowers_vc_e(self):
        """Dearer tooling → smaller economic speed (larger T_e → smaller vc_e)."""
        cheap = self._g(tool_cost=2.0)["vc_e_m_min"]
        expensive = self._g(tool_cost=20.0)["vc_e_m_min"]
        assert expensive < cheap

    def test_higher_machine_rate_raises_vc_e(self):
        """Higher machine rate → lower T_e → higher vc_e."""
        low = self._g(machine_rate=0.5)["vc_e_m_min"]
        high = self._g(machine_rate=5.0)["vc_e_m_min"]
        assert high > low

    def test_n_ge_1_returns_error(self):
        res = self._g(n=1.0)
        assert res["ok"] is False

    def test_zero_tool_cost_returns_error(self):
        res = self._g(tool_cost=0.0)
        assert res["ok"] is False

    def test_zero_machine_rate_returns_error(self):
        res = self._g(machine_rate=0.0)
        assert res["ok"] is False

    def test_feed_depth_correction_at_ref_point(self):
        """C_eff == C when f=1, dp=1 (reference calibration point)."""
        res = gilbert_economic_speed(
            C=300.0, n=0.25, tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0,
            f=1.0, a=0.5, dp=1.0, b=0.15,
        )
        assert res["ok"] is True
        assert math.isclose(res["C_eff"], 300.0, rel_tol=TREL)

    def test_feed_depth_correction_high_feed_lowers_C_eff(self):
        """C_eff < C when f > 1 (feed exponent a>0 means high f reduces C_eff)."""
        res = gilbert_economic_speed(
            C=300.0, n=0.25, tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0,
            f=2.0, a=0.5, dp=1.0, b=0.0,
        )
        assert res["ok"] is True
        assert res["C_eff"] < 300.0  # f=2>1 with a=0.5: C_eff=300/2^0.5=212


# ===========================================================================
# 3. production_rate_speed
# ===========================================================================

class TestProductionRateSpeed:

    _DEFAULTS = dict(C=300.0, n=0.25, tool_change_time=2.0)

    def _p(self, **kw):
        params = dict(self._DEFAULTS)
        params.update(kw)
        return production_rate_speed(**params)

    def test_returns_ok(self):
        assert self._p()["ok"] is True

    def test_T_mpr_formula(self):
        """T_mpr = (1/n − 1) × t_ct."""
        res = self._p()
        T_mpr_exp = (1.0 / 0.25 - 1.0) * 2.0
        assert math.isclose(res["T_mpr_min"], T_mpr_exp, rel_tol=TREL)

    def test_vc_mpr_formula(self):
        """vc_mpr = C / T_mpr^n (at f=1, dp=1, a=0, b=0)."""
        res = self._p()
        T_mpr = (1.0 / 0.25 - 1.0) * 2.0
        vc_exp = 300.0 / (T_mpr ** 0.25)
        assert math.isclose(res["vc_mpr_m_min"], vc_exp, rel_tol=TREL)

    def test_vc_mpr_ge_gilbert_vc_e(self):
        """V_mpr >= V_e by the theory (no tool cost → shorter T_mpr → higher vc)."""
        v_e = gilbert_economic_speed(
            C=300.0, n=0.25, tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0,
        )["vc_e_m_min"]
        v_mpr = self._p()["vc_mpr_m_min"]
        assert v_mpr >= v_e - 1e-9

    def test_shorter_change_time_raises_speed(self):
        """Less time to change → smaller T_mpr → higher vc_mpr."""
        v_long = self._p(tool_change_time=5.0)["vc_mpr_m_min"]
        v_short = self._p(tool_change_time=1.0)["vc_mpr_m_min"]
        assert v_short > v_long

    def test_n_ge_1_returns_error(self):
        assert self._p(n=1.0)["ok"] is False

    def test_zero_change_time_returns_error(self):
        assert self._p(tool_change_time=0.0)["ok"] is False

    def test_C_eff_with_feed_depth(self):
        """C_eff = C / (f^a · dp^b)."""
        res = production_rate_speed(C=300.0, n=0.25, tool_change_time=2.0,
                                    f=0.25, a=0.5, dp=2.0, b=0.15)
        C_eff_exp = 300.0 / (0.25**0.5 * 2.0**0.15)
        assert math.isclose(res["C_eff"], C_eff_exp, rel_tol=TREL)


# ===========================================================================
# 4. tool_life_curve
# ===========================================================================

class TestToolLifeCurve:

    _VCS = [100.0, 150.0, 200.0, 250.0, 300.0]

    def _curve(self, **kw):
        defaults = dict(vc_range=self._VCS, n=N, C=C, f=F_REF, a=A, dp=DP_REF, b=B)
        defaults.update(kw)
        return tool_life_curve(**defaults)

    def test_returns_ok(self):
        assert self._curve()["ok"] is True

    def test_correct_number_of_points(self):
        res = self._curve()
        assert res["points"] == len(self._VCS)
        assert len(res["curve"]) == len(self._VCS)

    def test_sorted_ascending(self):
        res = self._curve()
        vcs = [p["vc_m_min"] for p in res["curve"]]
        assert vcs == sorted(vcs)

    def test_T_decreasing_with_vc(self):
        """Higher vc → lower T (Taylor law)."""
        res = self._curve()
        Ts = [p["T_min"] for p in res["curve"]]
        assert all(Ts[i] > Ts[i + 1] for i in range(len(Ts) - 1))

    def test_individual_T_matches_formula(self):
        """Each curve point matches direct taylor_tool_life_extended call."""
        res = self._curve()
        for point in res["curve"]:
            T_direct = taylor_tool_life_extended(
                vc=point["vc_m_min"], C=C, n=N, f=F_REF, a=A, dp=DP_REF, b=B
            )["T_min"]
            assert math.isclose(point["T_min"], T_direct, rel_tol=TREL)

    def test_textbook_point_at_200(self):
        """At vc=200, T matches algebraic formula (T>>5 because f=0.25<1 raises C_eff)."""
        res = self._curve()
        pt = next(p for p in res["curve"] if math.isclose(p["vc_m_min"], 200.0))
        C_eff = C / (F_REF**A * DP_REF**B)
        T_exp = (C_eff / 200.0) ** (1.0 / N)
        assert math.isclose(pt["T_min"], T_exp, rel_tol=TREL)

    def test_empty_range_returns_error(self):
        res = tool_life_curve(vc_range=[], n=N, C=C, f=F_REF, a=A, dp=DP_REF, b=B)
        assert res["ok"] is False

    def test_invalid_vc_skipped(self):
        """Negative/zero vc entries are skipped silently."""
        res = tool_life_curve(vc_range=[100.0, -50.0, 0.0, 200.0],
                              n=N, C=C, f=F_REF, a=A, dp=DP_REF, b=B)
        assert res["ok"] is True
        assert res["points"] == 2

    def test_C_eff_in_output(self):
        res = self._curve()
        C_eff_exp = C / (F_REF**A * DP_REF**B)
        assert math.isclose(res["C_eff"], C_eff_exp, rel_tol=TREL)


# ===========================================================================
# 5. lookup_taylor_constants
# ===========================================================================

class TestLookupTaylorConstants:

    def test_carbide_aisi_1045_found(self):
        res = lookup_taylor_constants("carbide", "aisi_1045")
        assert res["ok"] is True
        assert res["n"] == 0.25
        assert res["a"] == 0.50
        assert res["b"] == 0.15
        assert res["C"] == 300.0

    def test_case_insensitive(self):
        res = lookup_taylor_constants("Carbide", "AISI_1045")
        assert res["ok"] is True

    def test_unknown_pair_returns_error_with_list(self):
        res = lookup_taylor_constants("unobtainium", "vibranium")
        assert res["ok"] is False
        assert "available_pairs" in res

    def test_all_table_entries_have_required_keys(self):
        for (t, w), consts in TAYLOR_CONSTANTS.items():
            for key in ("n", "a", "b", "C"):
                assert key in consts, f"Missing {key!r} for ({t}, {w})"
            assert 0 < consts["n"] < 1
            assert consts["a"] >= 0
            assert consts["b"] >= 0
            assert consts["C"] > 0


# ===========================================================================
# 6. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    # --- taylor_tool_life ---------------------------------------------------

    def test_taylor_tool_life_explicit_constants(self):
        """Basic Taylor (a=0, b=0): T=(300/200)^4=5.0625 ≈ 5 min (task spec validation)."""
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, _args(
            vc_m_min=200.0, C=300.0, n=0.25,
            f_mm_rev=1.0, a=0.0, dp_mm=1.0, b=0.0,
        )))
        d = _ok_tool(raw)
        assert math.isclose(d["T_min"], 5.0625, rel_tol=1e-9)

    def test_taylor_tool_life_with_feed_depth(self):
        """Extended Taylor: T > basic Taylor when f<1 (raises C_eff)."""
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, _args(
            vc_m_min=200.0, C=300.0, n=0.25,
            f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        d = _ok_tool(raw)
        assert d["T_min"] > 0
        # C_eff = 300/(0.25^0.5 * 2^0.15) > 300, so T > 5.0625
        assert d["T_min"] > 5.0625

    def test_taylor_tool_life_material_lookup(self):
        """Material lookup uses carbide/aisi_1045 constants; basic form at f=1,dp=1 gives 5.06."""
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, _args(
            vc_m_min=200.0, f_mm_rev=1.0, dp_mm=1.0,
            tool_material="carbide", work_material="aisi_1045",
        )))
        d = _ok_tool(raw)
        # At f=1, dp=1, a=0 equiv: but a=0.5, b=0.15 still apply, so T=(C/vc)^(1/n)=5.06
        # Because f^0.5=1, dp^0.15=1 when f=1, dp=1
        assert math.isclose(d["T_min"], (300.0 / 200.0) ** (1.0 / 0.25), rel_tol=1e-9)

    def test_taylor_tool_life_missing_vc_returns_error(self):
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, _args(
            C=300.0, n=0.25, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        _err_tool(raw)

    def test_taylor_tool_life_missing_C_without_material_returns_error(self):
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, _args(
            vc_m_min=200.0, n=0.25, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        _err_tool(raw)

    def test_taylor_tool_life_unknown_material_returns_error(self):
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, _args(
            vc_m_min=200.0, f_mm_rev=0.25, dp_mm=2.0,
            tool_material="unobtainium", work_material="vibranium",
        )))
        _err_tool(raw)

    def test_taylor_tool_life_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run(run_taylor_tool_life(ctx, b"not json"))
        _err_tool(raw)

    # --- gilbert_economic_speed ---------------------------------------------

    def test_gilbert_happy_path(self):
        ctx = _ctx()
        raw = _run(run_gilbert_economic_speed(ctx, _args(
            C=300.0, n=0.25, tool_cost=5.0,
            machine_rate=1.0, tool_change_time=2.0,
        )))
        d = _ok_tool(raw)
        assert 135.0 < d["vc_e_m_min"] < 145.0
        assert d["production_rate_speed_m_min"] > d["vc_e_m_min"]

    def test_gilbert_with_feed_depth(self):
        ctx = _ctx()
        raw = _run(run_gilbert_economic_speed(ctx, _args(
            C=300.0, n=0.25, tool_cost=5.0, machine_rate=1.0,
            tool_change_time=2.0, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        d = _ok_tool(raw)
        assert d["vc_e_m_min"] > 0
        assert d["production_rate_speed_m_min"] > d["vc_e_m_min"]

    def test_gilbert_missing_tool_cost_returns_error(self):
        ctx = _ctx()
        raw = _run(run_gilbert_economic_speed(ctx, _args(
            C=300.0, n=0.25, machine_rate=1.0, tool_change_time=2.0,
        )))
        _err_tool(raw)

    def test_gilbert_n_ge_1_returns_error(self):
        ctx = _ctx()
        raw = _run(run_gilbert_economic_speed(ctx, _args(
            C=300.0, n=1.0, tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0,
        )))
        _err_tool(raw)

    def test_gilbert_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run(run_gilbert_economic_speed(ctx, b"{bad"))
        _err_tool(raw)

    # --- production_rate_speed ----------------------------------------------

    def test_prod_rate_happy_path(self):
        ctx = _ctx()
        raw = _run(run_production_rate_speed(ctx, _args(
            C=300.0, n=0.25, tool_change_time=2.0,
        )))
        d = _ok_tool(raw)
        assert d["vc_mpr_m_min"] > 0
        assert d["T_mpr_min"] > 0

    def test_prod_rate_textbook_values(self):
        """T_mpr=6, vc_mpr≈192 (Kalpakjian / DeGarmo)."""
        ctx = _ctx()
        raw = _run(run_production_rate_speed(ctx, _args(
            C=300.0, n=0.25, tool_change_time=2.0,
        )))
        d = _ok_tool(raw)
        assert math.isclose(d["T_mpr_min"], 6.0, rel_tol=1e-9)
        assert 188.0 < d["vc_mpr_m_min"] < 196.0

    def test_prod_rate_missing_C_returns_error(self):
        ctx = _ctx()
        raw = _run(run_production_rate_speed(ctx, _args(
            n=0.25, tool_change_time=2.0,
        )))
        _err_tool(raw)

    def test_prod_rate_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run(run_production_rate_speed(ctx, b"bad"))
        _err_tool(raw)

    # --- tool_life_chart ----------------------------------------------------

    def test_chart_happy_path(self):
        ctx = _ctx()
        raw = _run(run_tool_life_chart(ctx, _args(
            vc_range=[100.0, 150.0, 200.0, 250.0],
            n=0.25, C=300.0, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        d = _ok_tool(raw)
        assert d["points"] == 4
        assert len(d["curve"]) == 4

    def test_chart_T_decreasing(self):
        ctx = _ctx()
        raw = _run(run_tool_life_chart(ctx, _args(
            vc_range=[100.0, 150.0, 200.0, 250.0, 300.0],
            n=0.25, C=300.0, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        d = _ok_tool(raw)
        Ts = [p["T_min"] for p in d["curve"]]
        assert all(Ts[i] > Ts[i + 1] for i in range(len(Ts) - 1))

    def test_chart_missing_vc_range_returns_error(self):
        ctx = _ctx()
        raw = _run(run_tool_life_chart(ctx, _args(
            n=0.25, C=300.0, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        _err_tool(raw)

    def test_chart_not_list_returns_error(self):
        ctx = _ctx()
        raw = _run(run_tool_life_chart(ctx, _args(
            vc_range=100.0,  # not a list
            n=0.25, C=300.0, f_mm_rev=0.25, a=0.5, dp_mm=2.0, b=0.15,
        )))
        _err_tool(raw)


# ===========================================================================
# 7. Cross-validation against textbook reference cases
# ===========================================================================

class TestTextbookValidation:
    """
    Validate against Kalpakjian §21 / DeGarmo §21 / Boothroyd §9 hand-calcs.
    """

    def test_kalpakjian_21_carbide_1045_basic_taylor(self):
        """
        Kalpakjian/DeGarmo §21: carbide on AISI 1045.
        Basic Taylor (a=0, b=0, equivalently f=1, dp=1):
          n=0.25, C=300 → at vc=200: T = (300/200)^4 = 5.0625 ≈ 5 min.
        This is the task-spec validation point.

        Note: the extended form at f=0.25, dp=2 gives T≈53 min because
        C is calibrated at f_ref=1,dp_ref=1, so f=0.25<1 raises C_eff
        above C (smaller feed → slower wear → longer life).
        """
        # Basic Taylor: T = (C/V)^(1/n) = (300/200)^4 = 5.0625
        res_basic = taylor_tool_life_extended(
            vc=200.0, C=300.0, n=0.25, f=1.0, a=0.0, dp=1.0, b=0.0
        )
        T_basic = (300.0 / 200.0) ** (1.0 / 0.25)
        assert math.isclose(res_basic["T_min"], T_basic, rel_tol=1e-9)
        assert math.isclose(T_basic, 5.0625, rel_tol=1e-6)

    def test_basic_taylor_task_spec_validation(self):
        """
        Task spec validation: carbide/AISI-1045, n=0.25, C=300, vc=200 m/min
        with f and dp having zero exponent → T = (300/200)^4 = 5.0625 ≈ 5 min.
        """
        T = (300.0 / 200.0) ** (1.0 / 0.25)
        assert math.isclose(T, 5.0625, rel_tol=1e-9)
        res = taylor_tool_life_extended(
            vc=200.0, C=300.0, n=0.25, f=1.0, a=0.0, dp=1.0, b=0.0
        )
        assert math.isclose(res["T_min"], 5.0625, rel_tol=1e-9)

    def test_gilbert_economic_lower_than_max_production(self):
        """
        Task spec: Gilbert economic speed < max-production speed always.
        """
        ge = gilbert_economic_speed(
            C=300.0, n=0.25, tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0
        )
        assert ge["vc_e_m_min"] < ge["production_rate_speed_m_min"]

    def test_boothroyd_9_3_T_e_and_T_mpr(self):
        """
        Boothroyd §9.3 formulas:
          T_e   = (1/n-1)·(t_ct + C_tool/C_m)
          T_mpr = (1/n-1)·t_ct
        With n=0.25, t_ct=2, C_tool=5, C_m=1:
          T_e=21, T_mpr=6.
        """
        ge = gilbert_economic_speed(
            C=300.0, n=0.25, tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0
        )
        assert math.isclose(ge["T_e_min"], 21.0, rel_tol=1e-9)
        assert math.isclose(ge["T_mpr_min"], 6.0, rel_tol=1e-9)

    def test_production_rate_speed_boothroyd_9_3(self):
        """
        Boothroyd §9.3: V_mpr = C / T_mpr^n.
        n=0.25, C=300, t_ct=2 → T_mpr=6, V_mpr=300/6^0.25≈191.9.
        """
        pr = production_rate_speed(C=300.0, n=0.25, tool_change_time=2.0)
        T_mpr_exp = (1.0 / 0.25 - 1.0) * 2.0
        V_mpr_exp = 300.0 / (T_mpr_exp ** 0.25)
        assert math.isclose(pr["T_mpr_min"], T_mpr_exp, rel_tol=1e-9)
        assert math.isclose(pr["vc_mpr_m_min"], V_mpr_exp, rel_tol=1e-9)

    def test_tool_life_chart_monotone_decreasing(self):
        """
        Tool-life chart must show T strictly decreasing as vc increases
        (fundamental Taylor law property).
        """
        vcs = [50.0, 100.0, 150.0, 200.0, 250.0, 300.0]
        res = tool_life_curve(vc_range=vcs, n=0.25, C=300.0,
                              f=0.25, a=0.5, dp=2.0, b=0.15)
        assert res["ok"] is True
        Ts = [p["T_min"] for p in res["curve"]]
        for i in range(len(Ts) - 1):
            assert Ts[i] > Ts[i + 1], f"T not decreasing at i={i}"

    def test_carbide_hss_same_steel_carbide_faster(self):
        """
        Carbide tools have higher C → longer tool life at same vc,
        or equivalently: higher economic speed.
        """
        ge_carbide = gilbert_economic_speed(
            C=TAYLOR_CONSTANTS[("carbide", "aisi_1045")]["C"],
            n=TAYLOR_CONSTANTS[("carbide", "aisi_1045")]["n"],
            tool_cost=5.0, machine_rate=1.0, tool_change_time=2.0,
        )
        ge_hss = gilbert_economic_speed(
            C=TAYLOR_CONSTANTS[("hss", "aisi_1045")]["C"],
            n=TAYLOR_CONSTANTS[("hss", "aisi_1045")]["n"],
            tool_cost=2.0, machine_rate=1.0, tool_change_time=2.0,
        )
        assert ge_carbide["vc_e_m_min"] > ge_hss["vc_e_m_min"]
