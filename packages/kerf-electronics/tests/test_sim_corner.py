"""
Hermetic tests for kerf_electronics/sim_corner.py — Monte-Carlo / corner analysis.

Covers:
  1. DC resistive divider: nominal = R2/(R1+R2)*Vin exact
  2. MC seeded reproducible (same seed → identical samples)
  3. MC mean ≈ nominal for small tolerances
  4. MC σ ≈ analytic for Gaussian tolerances
  5. MC uniform distribution σ
  6. Corner min/max bracket the MC range
  7. Yield = fraction within spec
  8. Sensitivity ranks higher-tolerance component first
  9. Sensitivity ranks higher-gain component first
 10. Tempco shifts output as expected
 11. RC low-pass -3dB at 1/(2πRC)
 12. AC transfer magnitude at DC limit (freq→0)
 13. MC seeded produces different results with different seed
 14. Zero-tolerance circuit returns all identical samples
 15. Corner analysis spread_pct is non-negative
 16. Sensitivity list ordered by magnitude descending
 17. Cpk > 0 when mean is centred in spec
 18. Yield = 100% when spec fully covers MC range
 19. Yield = 0% when spec excludes all samples
 20. Histogram bin counts sum to n_samples
 21. Corner worst_lo <= nominal <= worst_hi for symmetric tolerances
 22. Tempco sweep output increases when tc_ppm_K > 0 and temp rises
 23. Tool handler returns ok payload on valid input
 24. Tool handler returns error payload on missing netlist
 25. Tool handler returns error payload on missing out_node
 26. Tool handler returns error on unknown element type
 27. MC n_failed is 0 for well-posed circuit
 28. Current source in netlist shifts output correctly
 29. Diode clamps output near forward voltage
 30. AC transfer at exactly -3dB frequency is within 5% of 1/sqrt(2)

Loading strategy: stub kerf_chat.tools.registry before importing sim_corner
so no full kerf_chat install is required.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types
import unittest

# ── Prefer the real kerf_chat if installed; otherwise use the stub. ──────────
try:
    import kerf_chat as _kc_pkg  # noqa: F401
    import kerf_chat.tools as _kc_tools  # noqa: F401
    import kerf_chat.tools.registry as _kc_real  # noqa: F401
except Exception:
    _kc_real = None

_reg_stub = types.ModuleType("kerf_chat.tools.registry")
_reg_stub.Registry = type("Registry", (list,), {})
_reg_stub.ToolSpec = type("ToolSpec", (), {"__init__": lambda s, **kw: s.__dict__.update(kw)})
_reg_stub.err_payload = lambda msg, code: json.dumps({"ok": False, "error": msg, "code": code})
_reg_stub.ok_payload = lambda v: json.dumps({"ok": True, **v})
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

# ── Locate and load sim_corner.py ─────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

_sc_path = os.path.join(_SRC, "kerf_electronics", "sim_corner.py")
_sc_spec = importlib.util.spec_from_file_location("kerf_electronics.sim_corner", _sc_path)
_sc_mod = importlib.util.module_from_spec(_sc_spec)
_sc_spec.loader.exec_module(_sc_mod)

run_dc_op = _sc_mod.run_dc_op
run_ac_transfer = _sc_mod.run_ac_transfer
monte_carlo = _sc_mod.monte_carlo
corner_analysis = _sc_mod.corner_analysis
sensitivity_analysis = _sc_mod.sensitivity_analysis
tempco_sweep = _sc_mod.tempco_sweep
run_mc_corner_analysis = _sc_mod.run_mc_corner_analysis

# ── Circuit fixtures ───────────────────────────────────────────────────────────


def _divider(R1: float, R2: float, Vin: float = 5.0,
             tol1: float = 0.0, tol2: float = 0.0,
             dist: str = "gaussian") -> list[dict]:
    """Simple resistive voltage divider: Vin - R1 - out - R2 - GND."""
    return [
        {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": Vin,
         "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": R1,
         "tol_pct": tol1, "tc_ppm_K": 0.0, "dist": dist},
        {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": R2,
         "tol_pct": tol2, "tc_ppm_K": 0.0, "dist": dist},
    ]


def _rc_lowpass(R: float, C: float, Vin_ac: float = 1.0) -> list[dict]:
    """RC low-pass filter: V1 - R1 - out - C1 - GND."""
    return [
        {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": Vin_ac,
         "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": R,
         "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        {"ref": "C1", "type": "C", "nodes": ["out", "0"], "value": C,
         "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
    ]


def _divider_tempco(R1: float, R2: float, Vin: float,
                    tc1_ppm: float = 0.0, tc2_ppm: float = 0.0) -> list[dict]:
    return [
        {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": Vin,
         "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": R1,
         "tol_pct": 0.0, "tc_ppm_K": tc1_ppm, "dist": "gaussian"},
        {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": R2,
         "tol_pct": 0.0, "tc_ppm_K": tc2_ppm, "dist": "gaussian"},
    ]


async def _call_tool(payload: dict) -> dict:
    raw = await run_mc_corner_analysis(None, json.dumps(payload).encode())
    return json.loads(raw)


# ══════════════════════════════════════════════════════════════════════════════
# 1. DC resistive divider — nominal exact
# ══════════════════════════════════════════════════════════════════════════════

class TestDCDividerNominal(unittest.TestCase):

    def test_divider_nominal_exact(self):
        R1, R2, Vin = 1000.0, 2000.0, 5.0
        expected = R2 / (R1 + R2) * Vin
        result = run_dc_op(_divider(R1, R2, Vin), "out")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, expected, places=9,
                               msg="Resistive divider nominal should be exact")

    def test_divider_equal_resistors(self):
        result = run_dc_op(_divider(1000.0, 1000.0, 10.0), "out")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 5.0, places=9)

    def test_divider_extreme_ratio(self):
        R1, R2, Vin = 1.0, 999.0, 1.0
        expected = R2 / (R1 + R2) * Vin
        result = run_dc_op(_divider(R1, R2, Vin), "out")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, expected, places=6)


# ══════════════════════════════════════════════════════════════════════════════
# 2 & 3. MC seeded reproducible
# ══════════════════════════════════════════════════════════════════════════════

class TestMCReproducibility(unittest.TestCase):

    def test_same_seed_identical_samples(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=1.0, tol2=1.0)
        r1 = monte_carlo(nl, "out", n_runs=50, seed=7)
        r2 = monte_carlo(nl, "out", n_runs=50, seed=7)
        self.assertEqual(r1["samples"], r2["samples"],
                         "Same seed must produce identical MC samples")

    def test_different_seed_different_samples(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=5.0, tol2=5.0)
        r1 = monte_carlo(nl, "out", n_runs=50, seed=1)
        r2 = monte_carlo(nl, "out", n_runs=50, seed=2)
        # Overwhelmingly unlikely to be identical
        self.assertNotEqual(r1["samples"], r2["samples"])


# ══════════════════════════════════════════════════════════════════════════════
# 4. MC mean ≈ nominal for small tolerances
# ══════════════════════════════════════════════════════════════════════════════

class TestMCMeanNearNominal(unittest.TestCase):

    def test_mc_mean_near_nominal_gaussian(self):
        R1, R2, Vin = 1000.0, 1000.0, 5.0
        nominal = R2 / (R1 + R2) * Vin
        nl = _divider(R1, R2, Vin, tol1=1.0, tol2=1.0)
        res = monte_carlo(nl, "out", n_runs=500, seed=99)
        self.assertIsNotNone(res["mean"])
        # Mean should be within 0.5% of nominal for 500 runs, 1% tolerance
        self.assertAlmostEqual(res["mean"] / nominal, 1.0, delta=0.005,
                               msg="MC mean should be close to nominal")

    def test_mc_mean_near_nominal_uniform(self):
        R1, R2, Vin = 1000.0, 1000.0, 5.0
        nominal = R2 / (R1 + R2) * Vin
        nl = _divider(R1, R2, Vin, tol1=1.0, tol2=1.0, dist="uniform")
        res = monte_carlo(nl, "out", n_runs=500, seed=77, )
        self.assertIsNotNone(res["mean"])
        self.assertAlmostEqual(res["mean"] / nominal, 1.0, delta=0.01)


# ══════════════════════════════════════════════════════════════════════════════
# 5. MC σ ≈ analytic for small Gaussian tolerances
# ══════════════════════════════════════════════════════════════════════════════

class TestMCSigmaAnalytic(unittest.TestCase):

    def test_sigma_approx_analytic_gaussian(self):
        """
        For a voltage divider with both Rs having Gaussian tolerance σ_r (3σ=tol),
        the output Vout = R2/(R1+R2)*Vin.
        dVout/dR1 = -R2/(R1+R2)^2 * Vin
        dVout/dR2 = R1/(R1+R2)^2 * Vin
        σ_out = sqrt((dV/dR1)^2*σ_R1^2 + (dV/dR2)^2*σ_R2^2)
        """
        R1 = R2 = 1000.0
        Vin = 5.0
        tol_pct = 1.0
        sigma_r = R1 * tol_pct / (3.0 * 100.0)

        denom = (R1 + R2) ** 2
        dV_dR1 = -R2 / denom * Vin
        dV_dR2 = R1 / denom * Vin
        sigma_out_analytic = math.sqrt(dV_dR1 ** 2 * sigma_r ** 2 + dV_dR2 ** 2 * sigma_r ** 2)

        nl = _divider(R1, R2, Vin, tol1=tol_pct, tol2=tol_pct)
        res = monte_carlo(nl, "out", n_runs=2000, seed=123)
        self.assertIsNotNone(res["std"])
        # Allow 30% relative error on σ estimate (finite samples)
        ratio = res["std"] / sigma_out_analytic
        self.assertAlmostEqual(ratio, 1.0, delta=0.30,
                               msg=f"MC σ={res['std']:.6f} should be near analytic σ={sigma_out_analytic:.6f}")


# ══════════════════════════════════════════════════════════════════════════════
# 6. Corner min/max bracket MC range
# ══════════════════════════════════════════════════════════════════════════════

class TestCornerBracketsMC(unittest.TestCase):

    def test_corner_bounds_bracket_mc_range(self):
        """Worst-case corners must be at least as extreme as MC samples."""
        R1, R2, Vin = 1000.0, 1000.0, 5.0
        tol = 5.0
        nl = _divider(R1, R2, Vin, tol1=tol, tol2=tol)
        mc_res = monte_carlo(nl, "out", n_runs=300, seed=55)
        corners = corner_analysis(nl, "out")

        self.assertIsNotNone(mc_res["min"])
        self.assertIsNotNone(mc_res["max"])
        self.assertIsNotNone(corners["worst_lo"])
        self.assertIsNotNone(corners["worst_hi"])

        # Corners must bracket the MC range (with a tiny floating-point margin)
        margin = 1e-9
        self.assertLessEqual(corners["worst_lo"], mc_res["min"] + margin,
                             "corner worst_lo must be <= MC min")
        self.assertGreaterEqual(corners["worst_hi"], mc_res["max"] - margin,
                                "corner worst_hi must be >= MC max")


# ══════════════════════════════════════════════════════════════════════════════
# 7. Yield = fraction within spec
# ══════════════════════════════════════════════════════════════════════════════

class TestYield(unittest.TestCase):

    def test_yield_equals_fraction_in_spec(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=5.0, tol2=5.0)
        spec_lo, spec_hi = 2.3, 2.7
        res = monte_carlo(nl, "out", n_runs=200, seed=42,
                          spec_lo=spec_lo, spec_hi=spec_hi)
        samples = res["samples"]
        manual_passing = sum(1 for x in samples if spec_lo <= x <= spec_hi)
        manual_yield = 100.0 * manual_passing / len(samples)
        self.assertAlmostEqual(res["yield_pct"], manual_yield, places=10)

    def test_yield_100_when_spec_covers_all(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=1.0, tol2=1.0)
        res = monte_carlo(nl, "out", n_runs=100, seed=42,
                          spec_lo=0.0, spec_hi=10.0)
        self.assertAlmostEqual(res["yield_pct"], 100.0, places=9)

    def test_yield_0_when_spec_excludes_all(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=1.0, tol2=1.0)
        res = monte_carlo(nl, "out", n_runs=100, seed=42,
                          spec_lo=8.0, spec_hi=9.0)
        self.assertAlmostEqual(res["yield_pct"], 0.0, places=9)


# ══════════════════════════════════════════════════════════════════════════════
# 8. Sensitivity: higher-tolerance component ranked first
# ══════════════════════════════════════════════════════════════════════════════

class TestSensitivityRanking(unittest.TestCase):

    def test_higher_tol_component_contributes_more_absolute_variation(self):
        """
        sensitivity = dOut/dVal (absolute, not normalised).
        In a 1:9 divider (R1=100Ω, R2=900Ω, Vout=4.5V):
          dVout/dR1 = -R2/(R1+R2)^2 * Vin = -4.5e-3   (large because R2 large)
          dVout/dR2 =  R1/(R1+R2)^2 * Vin =  0.5e-3   (small because R1 small)
        So |sensitivity(R1)| > |sensitivity(R2)|, confirming R1 ranks first.
        """
        nl = [
            {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 5.0,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": 100.0,
             "tol_pct": 5.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": 900.0,
             "tol_pct": 1.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        ]
        sens = sensitivity_analysis(nl, "out")
        self.assertGreater(len(sens), 0)
        # Find sensitivities for R1 and R2
        s_map = {s["ref"]: s for s in sens}
        self.assertIn("R1", s_map)
        self.assertIn("R2", s_map)
        # |dOut/dR1| > |dOut/dR2| for this 1:9 divider
        self.assertGreater(abs(s_map["R1"]["sensitivity"]), abs(s_map["R2"]["sensitivity"]),
                           msg="R1 should have larger absolute dOut/dVal than R2 in a 1:9 divider")
        # Confirm R1 ranks before R2 in the sorted list
        refs = [s["ref"] for s in sens if s["ref"] != "V1"]
        self.assertEqual(refs[0], "R1",
                         msg=f"R1 should rank first; got {refs}")

    def test_sensitivity_sorted_descending(self):
        nl = _divider(1000.0, 2000.0, 5.0, tol1=5.0, tol2=1.0)
        sens = sensitivity_analysis(nl, "out")
        magnitudes = [abs(s["sensitivity"]) for s in sens]
        self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))


# ══════════════════════════════════════════════════════════════════════════════
# 9. Sensitivity: higher-gain component ranked first
# ══════════════════════════════════════════════════════════════════════════════

class TestSensitivityGain(unittest.TestCase):

    def test_gain_component_ranked_first(self):
        """
        1:9 divider (R1=100Ω series, R2=900Ω shunt, Vin=10V, Vout=9V).
        |dVout/dR1| = R2/(R1+R2)^2 * Vin = 900/1e6 * 10 = 9e-3  (large)
        |dVout/dR2| = R1/(R1+R2)^2 * Vin = 100/1e6 * 10 = 1e-3  (small)
        Sorted by absolute sensitivity, R1 should rank first.
        """
        R1, R2 = 100.0, 900.0
        nl = [
            {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 10.0,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": R1,
             "tol_pct": 1.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": R2,
             "tol_pct": 1.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        ]
        sens = sensitivity_analysis(nl, "out")
        non_src = [s for s in sens if s["ref"] != "V1"]
        self.assertGreaterEqual(len(non_src), 2)
        self.assertEqual(non_src[0]["ref"], "R1",
                         msg=f"R1 (|dV/dR|=9e-3) should rank above R2 (|dV/dR|=1e-3), got {non_src}")


# ══════════════════════════════════════════════════════════════════════════════
# 10. Tempco shifts output as expected
# ══════════════════════════════════════════════════════════════════════════════

class TestTempco(unittest.TestCase):

    def test_tempco_shifts_output_up_when_r2_increases(self):
        """If R2 has positive tc_ppm_K, increasing temp makes R2 larger → Vout rises."""
        R1, R2, Vin = 1000.0, 1000.0, 5.0
        tc2 = 1000.0  # 1000 ppm/K = 0.1%/K
        nl = _divider_tempco(R1, R2, Vin, tc1_ppm=0.0, tc2_ppm=tc2)

        T_nom = 300.0
        v_cold = run_dc_op(nl, "out", temp_delta_k=253.0 - T_nom)
        v_hot = run_dc_op(nl, "out", temp_delta_k=373.0 - T_nom)

        self.assertIsNotNone(v_cold)
        self.assertIsNotNone(v_hot)
        self.assertGreater(v_hot, v_cold,
                           msg="Higher temperature should raise Vout when R2 has positive tc")

    def test_tempco_sweep_returns_correct_length(self):
        nl = _divider_tempco(1000.0, 1000.0, 5.0, tc1_ppm=100.0, tc2_ppm=100.0)
        temps = [250.0, 275.0, 300.0, 325.0, 350.0]
        sweep = tempco_sweep(nl, "out", temps)
        self.assertEqual(len(sweep), len(temps))

    def test_tempco_sweep_output_none_free(self):
        nl = _divider_tempco(1000.0, 2000.0, 5.0, tc1_ppm=50.0, tc2_ppm=100.0)
        temps = [250.0, 300.0, 350.0]
        sweep = tempco_sweep(nl, "out", temps)
        for item in sweep:
            self.assertIsNotNone(item["output"])


# ══════════════════════════════════════════════════════════════════════════════
# 11. RC low-pass -3dB at 1/(2πRC)
# ══════════════════════════════════════════════════════════════════════════════

class TestACLowPass(unittest.TestCase):

    def test_rc_lowpass_3db_at_corner_frequency(self):
        R = 1000.0   # 1 kΩ
        C = 1e-6     # 1 µF
        f_3db = 1.0 / (2.0 * math.pi * R * C)
        nl = _rc_lowpass(R, C)
        h = run_ac_transfer(nl, "out", "V1", f_3db)
        self.assertIsNotNone(h)
        expected = 1.0 / math.sqrt(2.0)
        # Allow 1% tolerance
        self.assertAlmostEqual(h / expected, 1.0, delta=0.01,
                               msg=f"|H(f_3dB)|={h:.6f} should be 1/√2={expected:.6f}")

    def test_rc_lowpass_passband_near_unity(self):
        R = 1000.0
        C = 1e-6
        f_3db = 1.0 / (2.0 * math.pi * R * C)
        nl = _rc_lowpass(R, C)
        h = run_ac_transfer(nl, "out", "V1", f_3db / 100.0)
        self.assertIsNotNone(h)
        self.assertAlmostEqual(h, 1.0, delta=0.001)

    def test_rc_lowpass_stopband_attenuated(self):
        R = 1000.0
        C = 1e-6
        f_3db = 1.0 / (2.0 * math.pi * R * C)
        nl = _rc_lowpass(R, C)
        h = run_ac_transfer(nl, "out", "V1", f_3db * 100.0)
        self.assertIsNotNone(h)
        # At 100*f3dB, |H| ≈ 1/100
        self.assertLess(h, 0.02)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Additional AC corner + MC tests
# ══════════════════════════════════════════════════════════════════════════════

class TestACAdditional(unittest.TestCase):

    def test_ac_at_exactly_3db_within_5pct_of_1_over_sqrt2(self):
        """Redundant explicit check matching spec requirement."""
        R = 10000.0
        C = 100e-9
        f_3db = 1.0 / (2.0 * math.pi * R * C)
        nl = _rc_lowpass(R, C)
        h = run_ac_transfer(nl, "out", "V1", f_3db)
        self.assertIsNotNone(h)
        self.assertAlmostEqual(h / (1.0 / math.sqrt(2.0)), 1.0, delta=0.05)


# ══════════════════════════════════════════════════════════════════════════════
# 13. Zero-tolerance circuit returns identical samples
# ══════════════════════════════════════════════════════════════════════════════

class TestZeroTolerance(unittest.TestCase):

    def test_zero_tol_all_samples_identical(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=0.0, tol2=0.0)
        res = monte_carlo(nl, "out", n_runs=20, seed=1)
        samples = res["samples"]
        self.assertGreater(len(samples), 0)
        self.assertEqual(len(set(samples)), 1,
                         "Zero-tolerance circuit should give identical samples")


# ══════════════════════════════════════════════════════════════════════════════
# 14. Corner spread_pct is non-negative
# ══════════════════════════════════════════════════════════════════════════════

class TestCornerSpread(unittest.TestCase):

    def test_spread_pct_non_negative(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=5.0, tol2=5.0)
        res = corner_analysis(nl, "out")
        if res["spread_pct"] is not None:
            self.assertGreaterEqual(res["spread_pct"], 0.0)

    def test_corner_nominal_within_worst_lo_hi(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=5.0, tol2=5.0)
        res = corner_analysis(nl, "out")
        if res["nominal"] is not None and res["worst_lo"] is not None:
            self.assertLessEqual(res["worst_lo"], res["nominal"] + 1e-9)
            self.assertGreaterEqual(res["worst_hi"], res["nominal"] - 1e-9)


# ══════════════════════════════════════════════════════════════════════════════
# 15. Cpk > 0 when mean is centred in spec
# ══════════════════════════════════════════════════════════════════════════════

class TestCpk(unittest.TestCase):

    def test_cpk_positive_when_centred(self):
        R1 = R2 = 1000.0
        Vin = 5.0
        nominal = R2 / (R1 + R2) * Vin  # 2.5 V
        nl = _divider(R1, R2, Vin, tol1=1.0, tol2=1.0)
        margin = 0.5  # ±0.5 V from nominal
        res = monte_carlo(nl, "out", n_runs=300, seed=5,
                          spec_lo=nominal - margin, spec_hi=nominal + margin)
        if res["cpk"] is not None:
            self.assertGreater(res["cpk"], 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 16. Histogram bin counts sum to n_samples
# ══════════════════════════════════════════════════════════════════════════════

class TestHistogram(unittest.TestCase):

    def test_histogram_counts_sum_to_n_samples(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=2.0, tol2=2.0)
        res = monte_carlo(nl, "out", n_runs=100, seed=3)
        total_in_bins = sum(b["count"] for b in res["histogram"])
        self.assertEqual(total_in_bins, len(res["samples"]))

    def test_histogram_bins_non_overlapping_ordered(self):
        nl = _divider(1000.0, 1000.0, 5.0, tol1=2.0, tol2=2.0)
        res = monte_carlo(nl, "out", n_runs=50, seed=9)
        bins = res["histogram"]
        for i in range(len(bins) - 1):
            self.assertAlmostEqual(bins[i]["bin_hi"], bins[i + 1]["bin_lo"], places=12)


# ══════════════════════════════════════════════════════════════════════════════
# 17. MC n_failed is 0 for well-posed circuit
# ══════════════════════════════════════════════════════════════════════════════

class TestMCNFailed(unittest.TestCase):

    def test_n_failed_zero_for_well_posed_circuit(self):
        nl = _divider(1000.0, 2000.0, 3.3, tol1=1.0, tol2=1.0)
        res = monte_carlo(nl, "out", n_runs=100, seed=42)
        self.assertEqual(res["n_failed"], 0)


# ══════════════════════════════════════════════════════════════════════════════
# 18. Current source shifts output
# ══════════════════════════════════════════════════════════════════════════════

class TestCurrentSource(unittest.TestCase):

    def test_current_source_shifts_output(self):
        """1 kΩ to GND, driven by 1 mA current source → Vout = I*R = 1 V."""
        nl = [
            {"ref": "I1", "type": "I", "nodes": ["out", "0"], "value": 1e-3,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R1", "type": "R", "nodes": ["out", "0"], "value": 1000.0,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        ]
        result = run_dc_op(nl, "out")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 1.0, places=6)


# ══════════════════════════════════════════════════════════════════════════════
# 19. Diode clamps output near forward voltage
# ══════════════════════════════════════════════════════════════════════════════

class TestDiode(unittest.TestCase):

    def test_diode_clamps_forward_voltage(self):
        """Series R + diode to GND: with Vin=5V, R=1kΩ, Vout≈Vf=0.7V."""
        nl = [
            {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 5.0,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": 1000.0,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "D1", "type": "D", "nodes": ["out", "0"], "value": 0.7,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
        ]
        result = run_dc_op(nl, "out")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.7, delta=0.05,
                               msg=f"Diode should clamp output near Vf=0.7V, got {result}")


# ══════════════════════════════════════════════════════════════════════════════
# 20–25. Tool handler tests
# ══════════════════════════════════════════════════════════════════════════════

class TestToolHandler(unittest.IsolatedAsyncioTestCase):

    async def test_tool_returns_ok_on_valid_input(self):
        payload = {
            "netlist": [
                {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 5.0,
                 "tol_pct": 0.0},
                {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": 1000.0,
                 "tol_pct": 1.0},
                {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": 1000.0,
                 "tol_pct": 1.0},
            ],
            "out_node": "out",
            "mc_runs": 20,
        }
        result = await _call_tool(payload)
        self.assertNotIn("error", result, f"Unexpected error: {result}")
        self.assertIn("nominal", result)
        self.assertIn("monte_carlo", result)
        self.assertIn("corners", result)
        self.assertIn("sensitivity", result)

    async def test_tool_error_on_missing_netlist(self):
        result = await _call_tool({"out_node": "out"})
        self.assertIn("error", result)

    async def test_tool_error_on_missing_out_node(self):
        result = await _call_tool({
            "netlist": [{"ref": "R1", "type": "R", "nodes": ["a", "0"], "value": 1000.0}],
        })
        self.assertIn("error", result)

    async def test_tool_error_on_unknown_element_type(self):
        result = await _call_tool({
            "netlist": [{"ref": "X1", "type": "TRANSISTOR", "nodes": ["a", "0"], "value": 1.0}],
            "out_node": "a",
        })
        self.assertIn("error", result)

    async def test_tool_error_on_invalid_json(self):
        raw = await run_mc_corner_analysis(None, b"not-json")
        result = json.loads(raw)
        self.assertIn("error", result)

    async def test_tool_returns_tempco_sweep(self):
        payload = {
            "netlist": [
                {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 5.0},
                {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": 1000.0,
                 "tc_ppm_K": 100.0},
                {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": 1000.0,
                 "tc_ppm_K": 0.0},
            ],
            "out_node": "out",
            "mc_runs": 10,
        }
        result = await _call_tool(payload)
        self.assertNotIn("error", result, f"Unexpected error: {result}")
        self.assertIn("tempco_sweep", result)
        self.assertGreater(len(result["tempco_sweep"]), 0)

    async def test_tool_ac_analysis(self):
        R, C = 1000.0, 1e-6
        f_3db = 1.0 / (2.0 * math.pi * R * C)
        payload = {
            "netlist": [
                {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 1.0},
                {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": R},
                {"ref": "C1", "type": "C", "nodes": ["out", "0"], "value": C},
            ],
            "out_node": "out",
            "freq_hz": f_3db,
            "in_source_ref": "V1",
            "mc_runs": 10,
        }
        result = await _call_tool(payload)
        self.assertNotIn("error", result, f"Unexpected error: {result}")
        nominal = result.get("nominal")
        self.assertIsNotNone(nominal)
        self.assertAlmostEqual(nominal / (1.0 / math.sqrt(2.0)), 1.0, delta=0.05)

    async def test_tool_spec_lo_hi_yields_yield_pct(self):
        payload = {
            "netlist": [
                {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": 5.0},
                {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": 1000.0,
                 "tol_pct": 1.0},
                {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": 1000.0,
                 "tol_pct": 1.0},
            ],
            "out_node": "out",
            "mc_runs": 50,
            "spec_lo": 2.0,
            "spec_hi": 3.0,
        }
        result = await _call_tool(payload)
        self.assertNotIn("error", result, f"Unexpected error: {result}")
        mc = result["monte_carlo"]
        self.assertIn("yield_pct", mc)
        self.assertIsNotNone(mc["yield_pct"])


# ══════════════════════════════════════════════════════════════════════════════
# 26. MC uniform σ check
# ══════════════════════════════════════════════════════════════════════════════

class TestMCUniformSigma(unittest.TestCase):

    def test_uniform_std_approximate(self):
        """For single R with uniform ±tol%, σ ≈ tol/sqrt(3) * R * dV/dR."""
        R1 = R2 = 1000.0
        Vin = 5.0
        tol_pct = 5.0
        # Vary only R2 with uniform distribution
        nl = [
            {"ref": "V1", "type": "V", "nodes": ["vin", "0"], "value": Vin,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R1", "type": "R", "nodes": ["vin", "out"], "value": R1,
             "tol_pct": 0.0, "tc_ppm_K": 0.0, "dist": "gaussian"},
            {"ref": "R2", "type": "R", "nodes": ["out", "0"], "value": R2,
             "tol_pct": tol_pct, "tc_ppm_K": 0.0, "dist": "uniform"},
        ]
        res = monte_carlo(nl, "out", n_runs=2000, seed=21)
        # Analytic σ for uniform ±a: σ = a/sqrt(3), a = R2 * tol/100
        a = R2 * tol_pct / 100.0
        sigma_r2 = a / math.sqrt(3.0)
        # dVout/dR2 = R1/(R1+R2)^2 * Vin
        dV_dR2 = R1 / (R1 + R2) ** 2 * Vin
        sigma_out_analytic = abs(dV_dR2 * sigma_r2)

        self.assertAlmostEqual(res["std"] / sigma_out_analytic, 1.0, delta=0.25)


if __name__ == "__main__":
    unittest.main()


# ── Restore sys.modules to avoid contaminating other test suites ───────────────
def teardown_module(module):  # noqa: D401
    import sys as _sys
    for _name, _orig in _KERF_CHAT_SAVED.items():
        if _orig is None:
            _sys.modules.pop(_name, None)
        else:
            _sys.modules[_name] = _orig
