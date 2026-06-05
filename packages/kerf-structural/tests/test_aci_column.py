"""
Pytest oracles for structural_aci_column_axial and structural_aci_column_pm tools.

ACI 318-19 §22.4.2 short-column axial capacity
ACI 318-19 §21.2 P-M interaction diagram

All oracle values are analytically derived from the governing equations.
"""

from __future__ import annotations

import json
import asyncio
import math
import pytest

# ---------------------------------------------------------------------------
# Import the real kerf_cad_core functions directly (not via the tool wrapper)
# so we can use them for oracle derivation.
# ---------------------------------------------------------------------------
from kerf_cad_core.concrete.design import column_axial, column_pm_interaction


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _axial(b, h, Ast, fc=4000, fy=60000, col_type="tied", Pu=0.0):
    """Call column_axial with kwarg names matching design.py signature."""
    return column_axial(b=b, h=h, Ast=Ast, fc_psi=fc, fy_psi=fy, column_type=col_type)


def _pm(b, h, d, d_prime, As_top, As_bot, fc=4000, fy=60000, col_type="tied", n_points=20):
    return column_pm_interaction(
        b=b, h=h, d=d, d_prime=d_prime,
        As_top=As_top, As_bot=As_bot,
        fc_psi=fc, fy_psi=fy,
        column_type=col_type, n_points=n_points,
    )


# ===========================================================================
# TestColumnAxial — ACI 318-19 §22.4.2
# ===========================================================================

class TestColumnAxial:
    """Unit tests for column_axial().

    Reference column:  b = 16 in, h = 16 in, Ast = 4.0 in² (4 #9 bars),
                       f'c = 4000 psi, fy = 60000 psi.

    Analytical:
      Ag  = 256 in²
      Pn  = 0.85·4000·(256-4) + 60000·4 = 858,400 + 240,000 = 1,098,400 lb = 1098.4 kip
      phi_tied  = 0.65; factor = 0.80 → φPn = 0.65·0.80·1098.4 = 571.2 kip
      phi_spiral = 0.75; factor = 0.85 → φPn = 0.75·0.85·1098.4 = 699.9 kip
    """

    B, H, AST = 16.0, 16.0, 4.0

    def _oracle_Pn(self):
        Ag = self.B * self.H
        return (0.85 * 4000 * (Ag - self.AST) + 60000 * self.AST) / 1000.0  # kip

    def test_Pn_formula(self):
        res = _axial(self.B, self.H, self.AST)
        expected = self._oracle_Pn()
        assert res["Pn_kip"] == pytest.approx(expected, rel=1e-4)

    def test_phi_Pn_tied(self):
        res = _axial(self.B, self.H, self.AST, col_type="tied")
        expected = 0.65 * 0.80 * self._oracle_Pn()
        assert res["phi_Pn_kip"] == pytest.approx(expected, rel=1e-4)

    def test_phi_Pn_spiral(self):
        res = _axial(self.B, self.H, self.AST, col_type="spiral")
        expected = 0.75 * 0.85 * self._oracle_Pn()
        assert res["phi_Pn_kip"] == pytest.approx(expected, rel=1e-4)

    def test_phi_tied_value(self):
        res = _axial(self.B, self.H, self.AST, col_type="tied")
        assert res["phi"] == pytest.approx(0.65)

    def test_phi_spiral_value(self):
        res = _axial(self.B, self.H, self.AST, col_type="spiral")
        assert res["phi"] == pytest.approx(0.75)

    def test_Ag_correct(self):
        res = _axial(self.B, self.H, self.AST)
        assert res["Ag_in2"] == pytest.approx(self.B * self.H, rel=1e-6)

    def test_rho_g(self):
        res = _axial(self.B, self.H, self.AST)
        assert res["rho_g"] == pytest.approx(self.AST / (self.B * self.H), rel=1e-5)

    def test_rho_min_max_constants(self):
        res = _axial(self.B, self.H, self.AST)
        assert res["rho_min"] == pytest.approx(0.01)
        assert res["rho_max"] == pytest.approx(0.08)

    def test_low_rho_warning(self):
        # rho_g = 0.2/256 ≈ 0.00078 < 0.01 → warning
        res = _axial(self.B, self.H, Ast=0.2)
        assert any("minimum" in w for w in res["warnings"])

    def test_high_rho_warning(self):
        # rho_g = 256*0.09/1 → way over 0.08
        res = _axial(self.B, self.H, Ast=self.B * self.H * 0.09)
        assert any("maximum" in w for w in res["warnings"])

    def test_adequate_below_capacity(self):
        res = _axial(self.B, self.H, self.AST, Pu=100.0)
        assert res["phi_Pn_kip"] > 100.0  # should be ~571 kip

    def test_rho_normal_no_rho_warning(self):
        # rho_g = 4/256 = 0.0156 — within 0.01–0.08, no rho warnings
        res = _axial(self.B, self.H, self.AST)
        rho_warnings = [w for w in res["warnings"]
                        if "minimum" in w or "maximum" in w]
        assert rho_warnings == []

    def test_fc_variation(self):
        # Higher f'c should give higher Pn
        res_4 = _axial(12, 12, 2.0, fc=4000)
        res_6 = _axial(12, 12, 2.0, fc=6000)
        assert res_6["Pn_kip"] > res_4["Pn_kip"]


# ===========================================================================
# TestColumnPM — ACI 318-19 §22.4.2 / §21.2
# ===========================================================================

class TestColumnPM:
    """Tests for column_pm_interaction().

    Reference column:
      b=14 in, h=20 in, d=17.5 in, d'=2.5 in,
      As_top=2.0 in², As_bot=2.0 in²,
      f'c=4000 psi, fy=60000 psi, tied.
    """

    B, H, D, DP = 14.0, 20.0, 17.5, 2.5
    AS_TOP, AS_BOT = 2.0, 2.0
    FC, FY = 4000, 60000

    def _get(self, **kw):
        return _pm(
            self.B, self.H, self.D, self.DP,
            self.AS_TOP, self.AS_BOT,
            fc=self.FC, fy=self.FY,
            **kw,
        )

    def test_returns_points(self):
        res = self._get()
        assert "points" in res
        assert len(res["points"]) > 0

    def test_n_points_count(self):
        # n_points=20 → 21 sweep points + 1 pure-bending = 22
        res = self._get(n_points=20)
        assert len(res["points"]) == 22

    def test_points_have_required_keys(self):
        res = self._get()
        pt = res["points"][0]
        assert "phi_Pn_kip" in pt
        assert "phi_Mn_kipin" in pt
        assert "zone" in pt
        assert "eps_t" in pt

    def test_phi_Po_positive(self):
        res = self._get()
        assert res["phi_Po_kip"] > 0

    def test_phi_Po_reasonable(self):
        """phi_Po = phi_col * 0.80 * [0.85*f'c*(Ag-Ast) + fy*Ast]."""
        res = self._get()
        Ag = self.B * self.H
        Ast = self.AS_TOP + self.AS_BOT
        Pn = (0.85 * self.FC * (Ag - Ast) + self.FY * Ast) / 1000.0  # kip
        phi_Po = 0.65 * 0.80 * Pn  # tied, φ=0.65, factor=0.80
        assert res["phi_Po_kip"] == pytest.approx(phi_Po, rel=0.01)

    def test_pure_bending_Pn_near_zero(self):
        res = self._get()
        pure_bending_pt = res["points"][-1]
        # pure bending: phi_Pn ≈ 0
        assert pure_bending_pt["phi_Pn_kip"] == pytest.approx(0.0, abs=0.1)

    def test_pure_bending_moment_positive(self):
        res = self._get()
        pure_bending_pt = res["points"][-1]
        assert pure_bending_pt["phi_Mn_kipin"] > 0

    def test_phi_Mn0_matches_last_point(self):
        res = self._get()
        assert res["phi_Mn0_kipin"] == pytest.approx(res["points"][-1]["phi_Mn_kipin"], rel=1e-6)

    def test_high_compression_tension_controlled(self):
        """At very low c (pure bending end) zone should be tension-controlled."""
        res = self._get()
        last_pt = res["points"][-1]
        assert last_pt["zone"] == "tension-controlled"

    def test_compression_zone_at_top(self):
        """At high c (pure compression end) eps_t should be near zero or negative."""
        res = self._get()
        first_pt = res["points"][0]
        assert first_pt["eps_t"] < 0.005  # may be compression-controlled

    def test_spiral_higher_phi_Po(self):
        res_tied   = self._get(col_type="tied")
        res_spiral = self._get(col_type="spiral")
        assert res_spiral["phi_Po_kip"] > res_tied["phi_Po_kip"]

    def test_warnings_list_present(self):
        res = self._get()
        assert isinstance(res["warnings"], list)

    def test_slender_warning_triggered(self):
        """h > 22 in triggers slender-column warning."""
        res = _pm(
            b=14, h=24, d=21.5, d_prime=2.5,
            As_top=2.0, As_bot=2.0,
        )
        assert any("slender" in w.lower() for w in res["warnings"])

    def test_no_slender_warning_small_column(self):
        res = self._get()  # h=20 ≤ 22 → no slender warning
        assert not any("slender" in w.lower() for w in res["warnings"])


# ===========================================================================
# TestColumnAxialTool — tool wrapper (async via asyncio.run)
# ===========================================================================

class TestColumnAxialTool:
    """Smoke-test the tool wrappers through the async interface."""

    def _run(self, args_dict):
        from kerf_structural.aci_column import run_aci_column_axial
        from kerf_structural._compat import ProjectCtx
        ctx = ProjectCtx(project_id="test")
        raw = asyncio.get_event_loop().run_until_complete(
            run_aci_column_axial(ctx, json.dumps(args_dict).encode())
        )
        return json.loads(raw)

    def test_basic_call(self):
        out = self._run({"b": 16, "h": 16, "Ast": 4.0})
        assert out["ok"] is True
        assert "phi_Pn_kip" in out

    def test_adequate_flag_true(self):
        out = self._run({"b": 16, "h": 16, "Ast": 4.0, "Pu": 100.0})
        assert out["adequate"] is True

    def test_adequate_flag_false(self):
        out = self._run({"b": 8, "h": 8, "Ast": 0.5, "Pu": 2000.0})
        assert out["adequate"] is False

    def test_bad_args_missing_required(self):
        out = self._run({"b": 16})  # missing h, Ast
        # Should return error
        assert out.get("ok") is False or "error" in out or "reason" in out

    def test_code_section_present(self):
        out = self._run({"b": 14, "h": 14, "Ast": 3.0})
        assert "22.4.2" in out.get("code_section", "")


# ===========================================================================
# TestColumnPMTool — tool wrapper
# ===========================================================================

class TestColumnPMTool:
    """Smoke-test structural_aci_column_pm through async interface."""

    ARGS = {"b": 14, "h": 20, "d": 17.5, "d_prime": 2.5,
            "As_top": 2.0, "As_bot": 2.0}

    def _run(self, args_dict):
        from kerf_structural.aci_column import run_aci_column_pm
        from kerf_structural._compat import ProjectCtx
        ctx = ProjectCtx(project_id="test")
        raw = asyncio.get_event_loop().run_until_complete(
            run_aci_column_pm(ctx, json.dumps(args_dict).encode())
        )
        return json.loads(raw)

    def test_basic_call(self):
        out = self._run(self.ARGS)
        assert out["ok"] is True
        assert "interaction_pts" in out

    def test_interaction_pts_nonempty(self):
        out = self._run(self.ARGS)
        assert len(out["interaction_pts"]) > 0

    def test_each_pt_has_two_elements(self):
        out = self._run(self.ARGS)
        for pt in out["interaction_pts"]:
            assert len(pt) == 2

    def test_phi_Po_present(self):
        out = self._run(self.ARGS)
        assert "phi_Po_kip" in out
        assert out["phi_Po_kip"] > 0

    def test_phi_Mn0_present(self):
        out = self._run(self.ARGS)
        assert "phi_Mn0_kipin" in out
        assert out["phi_Mn0_kipin"] > 0

    def test_demand_check_inside(self):
        args = dict(self.ARGS)
        args["Pu"] = 50.0
        args["Mu_kip_in"] = 100.0
        out = self._run(args)
        assert "demand_ok" in out
        assert out["demand_ok"] is True

    def test_demand_check_outside(self):
        args = dict(self.ARGS)
        args["Pu"] = 1.0    # tiny axial
        args["Mu_kip_in"] = 1e9  # huge moment → outside
        out = self._run(args)
        assert out.get("demand_ok") is False

    def test_rho_g_correct(self):
        out = self._run(self.ARGS)
        expected = (self.ARGS["As_top"] + self.ARGS["As_bot"]) / (
            self.ARGS["b"] * self.ARGS["h"])
        # Tool rounds rho_g to 5 decimal places → rel tolerance 1e-2 is sufficient
        assert out["rho_g"] == pytest.approx(expected, rel=1e-2)

    def test_code_section_present(self):
        out = self._run(self.ARGS)
        assert "22.4.2" in out.get("code_section", "")

    def test_n_pts_total_reported(self):
        out = self._run(self.ARGS)
        assert out["n_pts_total"] > 0
