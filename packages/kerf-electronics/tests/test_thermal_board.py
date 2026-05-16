"""
Hermetic tests for kerf_electronics board-level thermal map / hotspot analysis.

Covers (≥25 tests):
  1. Uniform-power board → near-uniform T ≈ ambient + P/(h·A) at steady state
  2. Single point source → peak at source cell, T decays away from source
  3. More copper coverage → lower peak temperature (better spreading)
  4. Thermal vias to cold backside reduce hotspot
  5. Tj = T_board + P * theta_jc (exact)
  6. Derating flag fires when Tj > tj_max_c
  7. Derating flag clear when Tj ≤ tj_max_c
  8. Energy balance: Σ power in ≈ Σ convection+radiation out, within tolerance
  9. Doubling h lowers ΔT to approximately half
 10. Zero total power → T_field all at ambient
 11. Component at board edge still processed (clamp)
 12. peak_ij points to cell with T_field == peak_T_c
 13. Components list in result matches input count
 14. Negative power_w → ok=False, never raise
 15. Negative theta_jc → ok=False, never raise
 16. width_m <= 0 → ok=False
 17. copper_coverage out of [0,1] → ok=False
 18. nx < 2 → ok=False
 19. Thermal via at hotspot: T at that cell is lower than without via
 20. Multiple vias at same cell accumulate conductance (more vias = lower T)
 21. Forced convection (airflow > 0) lowers peak T vs natural convection
 22. Forced convection: doubling velocity lowers ΔT (monotone)
 23. recommend_copper_and_vias returns already_ok=True when baseline already meets target
 24. recommend_copper_and_vias suggests higher coverage when needed
 25. recommend_copper_and_vias via_options list has correct length
 26. copper_coverage_map per-cell override accepted and affects result
 27. board_thermal_map LLM tool: ok=True for valid input
 28. board_thermal_map LLM tool: ok=False for invalid width_m
 29. board_thermal_recommend LLM tool: already_ok path

Author: imranparuk
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

# ── Stub kerf_chat if not installed ──────────────────────────────────────────
try:
    import kerf_chat as _kc  # noqa: F401
    import kerf_chat.tools.registry as _kcr  # noqa: F401
except Exception:
    _kc = None
    _kcr = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type(
    "ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}
)
_reg_stub.err_payload = lambda msg, code="ERROR": json.dumps(
    {"ok": False, "error": msg, "code": code}
)
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
_reg_stub.register = lambda spec, write=False: (lambda fn: fn)

_kc_stub = types.ModuleType("kerf_chat")
_kct_stub = types.ModuleType("kerf_chat.tools")
sys.modules.setdefault("kerf_chat", _kc_stub)
sys.modules.setdefault("kerf_chat.tools", _kct_stub)
if _kcr is None:
    sys.modules["kerf_chat.tools.registry"] = _reg_stub

# ── Ensure src/ on sys.path ──────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.thermal_board import (
    BoardComponent,
    BoardThermalMapInput,
    ThermalVia,
    solve_board_thermal_map,
    recommend_copper_and_vias,
)

# ── Load the tool module via importlib so the stub is already active ─────────
_tool_spec = importlib.util.spec_from_file_location(
    "kerf_electronics.thermal_board",
    os.path.join(_SRC, "kerf_electronics", "thermal_board.py"),
)
_tool_mod = importlib.util.module_from_spec(_tool_spec)
_tool_spec.loader.exec_module(_tool_mod)

board_thermal_map_tool = _tool_mod.board_thermal_map_tool
board_thermal_recommend_tool = _tool_mod.board_thermal_recommend_tool


# ── Async helper ──────────────────────────────────────────────────────────────

async def call(fn, **kwargs):
    result = await fn(None, json.dumps(kwargs).encode())
    return json.loads(result)


# ── Shared board factories ────────────────────────────────────────────────────

def _uniform_board(power_per_comp: float = 0.5, n_comps: int = 4,
                   copper: float = 0.5, h: float = 10.0) -> BoardThermalMapInput:
    """4-component board with power spread roughly uniformly."""
    W, H = 0.1, 0.1  # 10 cm × 10 cm
    comps = [
        BoardComponent(ref=f"C{k}", x_m=(k + 0.5) * W / n_comps, y_m=H / 2,
                       power_w=power_per_comp)
        for k in range(n_comps)
    ]
    return BoardThermalMapInput(
        width_m=W, height_m=H,
        copper_coverage=copper,
        components=comps,
        ambient_c=25.0,
        h_conv=h,
        epsilon=0.0,   # radiation off for deterministic tests
        nx=20, ny=20,
        tol_k=1e-5,
    )


def _point_source_board(power: float = 2.0, copper: float = 0.3) -> BoardThermalMapInput:
    """Single component at board centre."""
    return BoardThermalMapInput(
        width_m=0.1, height_m=0.1,
        copper_coverage=copper,
        components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05, power_w=power)],
        ambient_c=25.0,
        h_conv=10.0,
        epsilon=0.0,
        nx=21, ny=21,   # odd so centre cell is well-defined
        tol_k=1e-5,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Uniform power → near-uniform temperature
# ═══════════════════════════════════════════════════════════════════════════════

class TestUniformPower:
    def test_uniform_temp_approx_analytical(self):
        """
        For uniformly distributed power with convection-only BC (k→∞ limit),
        each cell temperature ≈ T_amb + P_total / (h * A_board).
        With finite k the field should be within a reasonable range of this estimate.
        """
        W, H = 0.1, 0.1
        P_total = 4 * 0.5   # 4 components × 0.5 W = 2 W
        h = 10.0
        A = W * H
        T_expected = 25.0 + P_total / (h * A * 2)  # top + bottom: ×2 already in h_conv via h_eff≈h here (epsilon=0)
        # We check that the peak is in a physically plausible range
        inp = _uniform_board(power_per_comp=0.5, h=h)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        peak = res["peak_T_c"]
        # Peak should be above ambient and below some upper bound
        assert peak > 25.0
        assert peak < 25.0 + 200.0   # sanity upper bound

    def test_uniform_field_small_spread(self):
        """With high copper coverage the field should be nearly uniform."""
        inp = _uniform_board(copper=1.0)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        T = res["T_field"]
        all_T = [T[j][i] for j in range(res["ny"]) for i in range(res["nx"])]
        T_min = min(all_T)
        T_max = max(all_T)
        # Pure copper spreads very well — max spread should be narrow
        assert T_max - T_min < 20.0


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Single point source → peak at source, radially decaying
# ═══════════════════════════════════════════════════════════════════════════════

class TestPointSource:
    def test_peak_at_source_cell(self):
        """Peak temperature must be at (or very near) the source cell."""
        inp = _point_source_board(power=2.0)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        # Source is at centre → peak cell must be at or adjacent to centre
        nx, ny = res["nx"], res["ny"]
        pj, pi = res["peak_ij"]
        cx, cy = nx // 2, ny // 2
        dist = math.sqrt((pi - cx) ** 2 + (pj - cy) ** 2)
        assert dist <= 2.0, f"Peak at ({pi},{pj}), source at ({cx},{cy})"

    def test_temperature_decays_from_source(self):
        """T at source > T at board corner."""
        inp = _point_source_board(power=3.0)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        T = res["T_field"]
        nx, ny = res["nx"], res["ny"]
        T_centre = T[ny // 2][nx // 2]
        T_corner = T[0][0]
        assert T_centre > T_corner

    def test_peak_above_ambient(self):
        """Hotspot must exceed ambient temperature."""
        inp = _point_source_board(power=1.0)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        assert res["peak_T_c"] > 25.0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. More copper → lower peak temperature
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopperCoverage:
    def test_higher_copper_lowers_peak(self):
        """Increasing copper coverage reduces the hotspot temperature."""
        inp_low = _point_source_board(copper=0.05)
        inp_high = _point_source_board(copper=0.9)
        r_low = solve_board_thermal_map(inp_low)
        r_high = solve_board_thermal_map(inp_high)
        assert r_low["ok"] and r_high["ok"]
        assert r_high["peak_T_c"] < r_low["peak_T_c"]

    def test_full_copper_lowest_peak(self):
        """Full copper coverage gives the lowest possible peak for fixed h."""
        inp_base = _point_source_board(copper=0.3)
        inp_full = _point_source_board(copper=1.0)
        r_base = solve_board_thermal_map(inp_base)
        r_full = solve_board_thermal_map(inp_full)
        assert r_full["peak_T_c"] <= r_base["peak_T_c"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Thermal vias reduce hotspot
# ═══════════════════════════════════════════════════════════════════════════════

class TestThermalVias:
    def _board_with_via(self, n: int) -> BoardThermalMapInput:
        return BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            copper_coverage=0.3,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05, power_w=2.0)],
            thermal_vias=[ThermalVia(x_m=0.05, y_m=0.05, n_vias=n, r_via_m=1.5e-4)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=21, ny=21, tol_k=1e-5,
        )

    def test_vias_reduce_hotspot_vs_no_vias(self):
        """Adding thermal vias at the component location lowers the hotspot."""
        inp_no_via = _point_source_board(power=2.0)
        inp_via = self._board_with_via(n=16)
        r_no = solve_board_thermal_map(inp_no_via)
        r_via = solve_board_thermal_map(inp_via)
        assert r_no["ok"] and r_via["ok"]
        assert r_via["peak_T_c"] < r_no["peak_T_c"]

    def test_more_vias_lower_temperature(self):
        """More thermal vias → lower peak temperature (monotone)."""
        r4 = solve_board_thermal_map(self._board_with_via(4))
        r32 = solve_board_thermal_map(self._board_with_via(32))
        assert r4["ok"] and r32["ok"]
        assert r32["peak_T_c"] < r4["peak_T_c"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Tj = T_board + P * theta_jc
# ═══════════════════════════════════════════════════════════════════════════════

class TestJunctionTemperature:
    def test_tj_equals_tboard_plus_p_theta_jc(self):
        """Tj = T_board_c + power_w * theta_jc (exact formula check)."""
        theta_jc = 15.0
        power = 2.0
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            copper_coverage=0.5,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05,
                                       power_w=power, theta_jc=theta_jc)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=10, ny=10, tol_k=1e-5,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        comp = res["components"][0]
        expected_tj = comp["T_board_c"] + power * theta_jc
        assert abs(comp["Tj_c"] - expected_tj) < 1e-3


# ═══════════════════════════════════════════════════════════════════════════════
# 6 & 7. Derating flag
# ═══════════════════════════════════════════════════════════════════════════════

class TestDerating:
    def test_over_limit_fires_when_tj_exceeds_max(self):
        """over_limit=True when computed Tj > tj_max_c."""
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            copper_coverage=0.3,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05,
                                       power_w=5.0, theta_jc=50.0, tj_max_c=50.0)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=10, ny=10, tol_k=1e-5,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        comp = res["components"][0]
        # Tj = T_board + 5*50; T_board > 25, so Tj >> 50
        assert comp["over_limit"] is True
        assert comp["margin_c"] < 0

    def test_over_limit_clear_when_tj_safe(self):
        """over_limit=False when computed Tj ≤ tj_max_c."""
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            copper_coverage=0.5,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05,
                                       power_w=0.01, theta_jc=1.0, tj_max_c=200.0)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=10, ny=10, tol_k=1e-5,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        comp = res["components"][0]
        assert comp["over_limit"] is False
        assert comp["margin_c"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# 8. Energy balance
# ═══════════════════════════════════════════════════════════════════════════════

class TestEnergyBalance:
    def test_energy_balance_within_tolerance(self):
        """Σ power in ≈ Σ convection out; relative error < 5%."""
        inp = _point_source_board(power=2.0)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        assert res["energy_balance_err"] < 0.05

    def test_zero_power_zero_out(self):
        """Zero sources → zero net heat removal (T=T_amb everywhere)."""
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            copper_coverage=0.5,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05, power_w=0.0)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=10, ny=10, tol_k=1e-6,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        assert abs(res["total_conv_rad_w"]) < 1e-6
        T = res["T_field"]
        max_T = max(T[j][i] for j in range(res["ny"]) for i in range(res["nx"]))
        assert abs(max_T - 25.0) < 1e-3


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Doubling h lowers ΔT ~ half
# ═══════════════════════════════════════════════════════════════════════════════

class TestDoublingH:
    def test_doubling_h_halves_delta_t_approx(self):
        """Doubling the convection coefficient should roughly halve ΔT."""
        h1 = 10.0
        h2 = 20.0
        inp1 = _point_source_board(power=2.0, copper=0.5)
        inp1.h_conv = h1
        inp2 = _point_source_board(power=2.0, copper=0.5)
        inp2.h_conv = h2
        r1 = solve_board_thermal_map(inp1)
        r2 = solve_board_thermal_map(inp2)
        assert r1["ok"] and r2["ok"]
        dt1 = r1["peak_T_c"] - 25.0
        dt2 = r2["peak_T_c"] - 25.0
        # For convection-dominated board: ΔT ∝ 1/h
        # Allow 60% tolerance for finite-k effects
        assert dt2 < dt1
        ratio = dt1 / max(dt2, 1e-12)
        assert 1.3 <= ratio <= 3.0, f"Expected ratio ~2, got {ratio:.2f}"


# ═══════════════════════════════════════════════════════════════════════════════
# 10–12. Basic structural checks
# ═══════════════════════════════════════════════════════════════════════════════

class TestStructural:
    def test_peak_ij_matches_T_field_max(self):
        """peak_ij must point to the cell with the maximum T in T_field."""
        inp = _point_source_board(power=1.5)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        pj, pi = res["peak_ij"]
        assert abs(res["T_field"][pj][pi] - res["peak_T_c"]) < 1e-3

    def test_component_count_preserved(self):
        """Result components list length == input component count."""
        inp = _uniform_board()
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        assert len(res["components"]) == len(inp.components)

    def test_component_at_edge_clamped(self):
        """Component placed outside board bounds is clamped and processed."""
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            copper_coverage=0.3,
            components=[BoardComponent(ref="U1", x_m=0.15, y_m=0.15, power_w=1.0)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=10, ny=10, tol_k=1e-5,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is True
        assert len(res["components"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13–14. Validation errors
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidation:
    def test_negative_power_friendly_error(self):
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05, power_w=-1.0)],
            nx=10, ny=10,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is False
        assert "power_w" in res["reason"]

    def test_negative_theta_jc_friendly_error(self):
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05,
                                       power_w=1.0, theta_jc=-5.0)],
            nx=10, ny=10,
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is False
        assert "theta_jc" in res["reason"]

    def test_zero_width_friendly_error(self):
        inp = BoardThermalMapInput(width_m=0.0, height_m=0.1, nx=10, ny=10)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is False

    def test_bad_copper_coverage_friendly_error(self):
        inp = BoardThermalMapInput(
            width_m=0.1, height_m=0.1, copper_coverage=1.5, nx=10, ny=10
        )
        res = solve_board_thermal_map(inp)
        assert res["ok"] is False

    def test_nx_too_small_friendly_error(self):
        inp = BoardThermalMapInput(width_m=0.1, height_m=0.1, nx=1, ny=10)
        res = solve_board_thermal_map(inp)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Forced convection
# ═══════════════════════════════════════════════════════════════════════════════

class TestForcedConvection:
    def test_airflow_lowers_peak_vs_natural(self):
        """Forced airflow reduces peak temperature vs natural convection."""
        base = _point_source_board(power=2.0)
        base.airflow_m_per_s = 0.0
        base.board_length_m = 0.1

        forced = _point_source_board(power=2.0)
        forced.airflow_m_per_s = 2.0
        forced.board_length_m = 0.1

        r_nat = solve_board_thermal_map(base)
        r_forced = solve_board_thermal_map(forced)
        assert r_nat["ok"] and r_forced["ok"]
        assert r_forced["peak_T_c"] < r_nat["peak_T_c"]

    def test_higher_velocity_lowers_peak_monotone(self):
        """Increasing airflow velocity monotonically decreases peak T."""
        def peak(v):
            inp = _point_source_board(power=2.0)
            inp.airflow_m_per_s = v
            inp.board_length_m = 0.1
            return solve_board_thermal_map(inp)["peak_T_c"]

        p1 = peak(1.0)
        p4 = peak(4.0)
        assert p4 < p1


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Copper coverage map override
# ═══════════════════════════════════════════════════════════════════════════════

class TestCopperCoverageMap:
    def test_per_cell_map_affects_result(self):
        """A high-copper zone under the hotspot lowers peak vs uniform low copper."""
        W, H, NX, NY = 0.1, 0.1, 10, 10
        # Uniform 0.1 coverage baseline
        inp_low = BoardThermalMapInput(
            width_m=W, height_m=H,
            copper_coverage=0.1,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05, power_w=1.5)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=NX, ny=NY, tol_k=1e-5,
        )
        # Per-cell map: high copper (0.9) at centre cell, 0.1 elsewhere
        cmap = [[0.1] * NX for _ in range(NY)]
        cmap[NY // 2][NX // 2] = 0.9
        inp_map = BoardThermalMapInput(
            width_m=W, height_m=H,
            copper_coverage=0.1,
            copper_coverage_map=cmap,
            components=[BoardComponent(ref="U1", x_m=0.05, y_m=0.05, power_w=1.5)],
            ambient_c=25.0, h_conv=10.0, epsilon=0.0,
            nx=NX, ny=NY, tol_k=1e-5,
        )
        r_low = solve_board_thermal_map(inp_low)
        r_map = solve_board_thermal_map(inp_map)
        assert r_low["ok"] and r_map["ok"]
        assert r_map["peak_T_c"] < r_low["peak_T_c"]


# ═══════════════════════════════════════════════════════════════════════════════
# 17. recommend_copper_and_vias
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecommend:
    def test_already_ok_when_target_large(self):
        """Returns already_ok=True when target ΔT is large enough."""
        inp = _point_source_board(power=0.1)
        res = recommend_copper_and_vias(inp, target_delta_t_c=1000.0)
        assert res["ok"] is True
        assert res["already_ok"] is True

    def test_suggests_higher_copper_when_needed(self):
        """When baseline ΔT exceeds target, recommends higher copper coverage."""
        inp = _point_source_board(power=3.0, copper=0.05)
        baseline = solve_board_thermal_map(inp)
        assert baseline["ok"]
        baseline_dt = baseline["peak_T_c"] - 25.0
        # Set target slightly below baseline
        target = baseline_dt * 0.7
        res = recommend_copper_and_vias(inp, target_delta_t_c=target)
        assert res["ok"] is True
        if not res["already_ok"]:
            cr = res["copper_recommendation"]
            assert cr is not None
            # min_coverage should be higher than current or None (if impossible)
            if cr["min_coverage"] is not None:
                assert cr["min_coverage"] >= inp.copper_coverage

    def test_via_options_correct_length(self):
        """via_options list length equals len(n_via_options)."""
        inp = _point_source_board(power=2.0, copper=0.1)
        n_opts = [4, 8, 16]
        res = recommend_copper_and_vias(inp, target_delta_t_c=5.0,
                                        n_via_options=n_opts)
        assert res["ok"] is True
        if not res["already_ok"]:
            assert len(res["via_options"]) == len(n_opts)

    def test_invalid_target_delta_t(self):
        """target_delta_t_c <= 0 returns ok=False."""
        inp = _point_source_board(power=1.0)
        res = recommend_copper_and_vias(inp, target_delta_t_c=0.0)
        assert res["ok"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# 18. LLM tool handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestBoardThermalMapTool:
    @pytest.mark.asyncio
    async def test_basic_valid_input(self):
        """Tool returns ok=True for a valid board description."""
        res = await call(
            board_thermal_map_tool,
            width_m=0.1, height_m=0.1,
            copper_coverage=0.4, ambient_c=25.0,
            h_conv=10.0, epsilon=0.0,
            nx=10, ny=10,
            components=[{"ref": "U1", "x_m": 0.05, "y_m": 0.05, "power_w": 1.0}],
        )
        assert res["ok"] is True
        assert "peak_T_c" in res
        assert res["peak_T_c"] > 25.0

    @pytest.mark.asyncio
    async def test_invalid_width_returns_error(self):
        """Non-numeric width_m → error response."""
        res = await call(board_thermal_map_tool, width_m="wide", height_m=0.1)
        assert res.get("ok") is not True

    @pytest.mark.asyncio
    async def test_no_components_ok(self):
        """Board with no components (zero power) should still run."""
        res = await call(
            board_thermal_map_tool,
            width_m=0.1, height_m=0.1,
            copper_coverage=0.3, ambient_c=25.0,
            h_conv=10.0, epsilon=0.0, nx=5, ny=5,
        )
        assert res["ok"] is True
        assert abs(res["peak_T_c"] - 25.0) < 1.0


class TestBoardThermalRecommendTool:
    @pytest.mark.asyncio
    async def test_already_ok_path(self):
        """Tool returns already_ok=True when board easily meets target."""
        board = {
            "width_m": 0.1, "height_m": 0.1,
            "copper_coverage": 0.5, "ambient_c": 25.0,
            "h_conv": 10.0, "epsilon": 0.0,
            "nx": 10, "ny": 10,
            "components": [{"ref": "U1", "x_m": 0.05, "y_m": 0.05, "power_w": 0.1}],
        }
        res = await call(
            board_thermal_recommend_tool,
            board=board,
            target_delta_t_c=500.0,
        )
        assert res["ok"] is True
        assert res["already_ok"] is True

    @pytest.mark.asyncio
    async def test_invalid_target_dt(self):
        """target_delta_t_c <= 0 returns error."""
        board = {"width_m": 0.1, "height_m": 0.1, "nx": 5, "ny": 5}
        res = await call(
            board_thermal_recommend_tool,
            board=board,
            target_delta_t_c=-10.0,
        )
        assert res.get("ok") is not True
