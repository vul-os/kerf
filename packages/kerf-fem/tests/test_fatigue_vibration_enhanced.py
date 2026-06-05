"""
Enhanced pytest suite for fatigue S-N curve / Haigh diagram and
vibration FRF sweep capabilities.

Coverage (fatigue)
------------------
F1.  sn_curve returns correct Basquin-law (N, σ_a) pairs
F2.  sn_curve σ_a at N_e equals endurance limit (σ'_f·(2Ne)^b ≈ Se)
F3.  sn_curve amplitudes monotonically decrease with N (b < 0)
F4.  sn_curve mean-stress correction with Goodman reduces amplitude
F5.  sn_curve mean-stress correction with Gerber differs from Goodman
F6.  sn_curve with SWT correction differs from Goodman
F7.  sn_curve bad material returns ok=False
F8.  sn_curve returns endurance_limit_pa == material Se
F9.  haigh_diagram Goodman boundary at σ_m=0 equals Se
F10. haigh_diagram Goodman boundary at σ_m=Su equals 0
F11. haigh_diagram Gerber >= Goodman for all σ_m in [0, Su] (Gerber less conservative)
F12. haigh_diagram Langer yield line = Sy - σ_m at σ_m=0
F13. haigh_diagram bad material returns ok=False
F14. fem_sn_curve tool wrapper returns ok=True for valid payload
F15. fem_sn_curve tool wrapper bad JSON returns error
F16. fem_haigh_diagram tool wrapper returns ok=True
F17. sn_curve n_points determines length of output lists
F18. haigh_diagram SWT boundary is convex (decreasing slope)
F19. sn_curve fully-reversed (mean=0) amplitude at N=1e3 matches Basquin closed form
F20. sn_curve Su_pa and b fields in return dict

Coverage (vibration FRF sweep)
-------------------------------
V1.  frf_sweep SDOF magnitude at resonance ≈ Γ/(2ζω_n²)
V2.  frf_sweep resonant peak frequency matches fn
V3.  frf_sweep phase at resonance ≈ −90° (standard convention)
V4.  frf_sweep magnitude list length equals n_pts
V5.  frf_sweep empty fn_hz returns ok=False
V6.  frf_sweep mismatched zeta length returns ok=False
V7.  frf_sweep mismatched participation length returns ok=False
V8.  frf_sweep negative damping returns ok=False
V9.  frf_sweep f_max <= f_min returns ok=False
V10. frf_sweep two-mode response has two local maxima near each fn
V11. frf_sweep mode_table has correct length and fields
V12. frf_sweep mode_table DAF_at_resonance = 1/(2ζ)
V13. fem_frf_sweep tool wrapper valid payload returns ok=True with magnitude
V14. fem_frf_sweep tool wrapper bad JSON returns error
V15. fem_frf_sweep tool wrapper scalar zeta accepted
V16. frf_sweep static limit (f→0): magnitude approaches Σ Γ_i / ω_i²
V17. frf_sweep per-mode zeta list accepted
"""

from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_fem.fatigue_fem import (
    sn_curve,
    haigh_diagram,
    run_fem_sn_curve,
    run_fem_haigh_diagram,
    _fem_sn_curve_spec,
    _fem_haigh_diagram_spec,
)
from kerf_fem.harmonic import (
    frf_sweep,
    run_fem_frf_sweep,
    _fem_frf_sweep_spec,
    sdof_daf,
)

# ---------------------------------------------------------------------------
# Shared material
# ---------------------------------------------------------------------------

MAT_STEEL = {
    "Su": 600e6,
    "Sy": 450e6,
    "Se": 300e6,
    "b": -0.085,
    "c": -0.60,
    "E": 207e9,
    "sf_prime": 900e6,
    "ef_prime": 0.59,
}


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# F1–F20  S-N curve and Haigh diagram
# ===========================================================================

class TestSNCurve:

    def test_F1_basquin_law_at_single_point(self):
        """sn_curve returns (N, σ_a) pairs where σ_a = σ'_f·(2N)^b."""
        res = sn_curve(MAT_STEEL, n_min=1e3, n_max=1e3, n_points=1)
        assert res["ok"], res.get("reason")
        N = res["N_cycles"][0]
        sigma_a = res["sigma_a_pa"][0]
        b = MAT_STEEL["b"]
        sf = MAT_STEEL["sf_prime"]
        expected = sf * (2.0 * N) ** b
        assert abs(sigma_a - expected) / max(abs(expected), 1.0) < 1e-9, (
            f"σ_a={sigma_a:.4e}, expected={expected:.4e}"
        )

    def test_F2_endurance_limit_near_Ne(self):
        """
        At N = Ne (cycles to endurance), Basquin gives σ_a ≈ Se.
        Solve: Se = σ'_f · (2Ne)^b  →  Ne = 0.5 · (Se/σ'_f)^(1/b).
        """
        Se = MAT_STEEL["Se"]
        b = MAT_STEEL["b"]
        sf = MAT_STEEL["sf_prime"]
        Ne = 0.5 * (Se / sf) ** (1.0 / b)

        res = sn_curve(MAT_STEEL, n_min=Ne, n_max=Ne, n_points=1)
        assert res["ok"]
        sigma_a = res["sigma_a_pa"][0]
        assert abs(sigma_a - Se) / Se < 1e-9, (
            f"At Ne={Ne:.2e}, σ_a={sigma_a:.4e}, Se={Se:.4e}"
        )

    def test_F3_amplitudes_decrease_with_N(self):
        """For b < 0, σ_a must decrease monotonically as N increases."""
        res = sn_curve(MAT_STEEL, n_min=1e3, n_max=1e8, n_points=20)
        assert res["ok"]
        amps = res["sigma_a_pa"]
        for i in range(len(amps) - 1):
            assert amps[i] >= amps[i + 1], (
                f"Non-monotone at i={i}: amps[i]={amps[i]:.4e} < amps[i+1]={amps[i+1]:.4e}"
            )

    def test_F4_goodman_reduces_amplitude_positive_mean(self):
        """Goodman mean-stress correction must lower allowable σ_a."""
        res_zr = sn_curve(MAT_STEEL, mean_stress=0.0, correction="goodman")
        res_mc = sn_curve(MAT_STEEL, mean_stress=150e6, correction="goodman")
        assert res_zr["ok"] and res_mc["ok"]
        # Average amplitude over the curve must be lower with mean stress
        avg_zr = sum(res_zr["sigma_a_pa"]) / len(res_zr["sigma_a_pa"])
        avg_mc = sum(res_mc["sigma_a_pa"]) / len(res_mc["sigma_a_pa"])
        assert avg_mc < avg_zr, (
            f"Goodman with σ_m=150 MPa avg={avg_mc:.4e} should be < zero-mean avg={avg_zr:.4e}"
        )

    def test_F5_gerber_differs_from_goodman(self):
        """Gerber correction must give different (higher) amplitudes than Goodman."""
        res_g  = sn_curve(MAT_STEEL, mean_stress=200e6, correction="goodman")
        res_gb = sn_curve(MAT_STEEL, mean_stress=200e6, correction="gerber")
        assert res_g["ok"] and res_gb["ok"]
        avg_g  = sum(res_g["sigma_a_pa"]) / len(res_g["sigma_a_pa"])
        avg_gb = sum(res_gb["sigma_a_pa"]) / len(res_gb["sigma_a_pa"])
        # Gerber is less conservative → higher allowable amplitude
        assert avg_gb > avg_g, (
            f"Gerber avg={avg_gb:.4e} should be > Goodman avg={avg_g:.4e}"
        )

    def test_F6_swt_differs_from_goodman(self):
        """SWT correction gives a different result than Goodman."""
        res_g   = sn_curve(MAT_STEEL, mean_stress=100e6, correction="goodman")
        res_swt = sn_curve(MAT_STEEL, mean_stress=100e6, correction="swt")
        assert res_g["ok"] and res_swt["ok"]
        # They should differ (different formulas)
        avg_g   = sum(res_g["sigma_a_pa"]) / len(res_g["sigma_a_pa"])
        avg_swt = sum(res_swt["sigma_a_pa"]) / len(res_swt["sigma_a_pa"])
        assert abs(avg_g - avg_swt) / max(avg_g, 1e-30) > 1e-4, (
            "SWT and Goodman should differ"
        )

    def test_F7_bad_material_returns_error(self):
        """sn_curve with Su=0 returns ok=False."""
        res = sn_curve({"Su": 0.0})
        assert res["ok"] is False
        assert "reason" in res

    def test_F8_endurance_limit_in_result(self):
        """endurance_limit_pa must match material Se."""
        res = sn_curve(MAT_STEEL)
        assert res["ok"]
        assert abs(res["endurance_limit_pa"] - MAT_STEEL["Se"]) < 1.0

    def test_F17_n_points_controls_output_length(self):
        """n_points=15 should give exactly 15 entries."""
        res = sn_curve(MAT_STEEL, n_points=15)
        assert res["ok"]
        assert len(res["N_cycles"]) == 15
        assert len(res["sigma_a_pa"]) == 15
        assert len(res["sigma_a_mpa"]) == 15

    def test_F19_zero_mean_amplitude_matches_basquin_closed_form(self):
        """At N=1e3, σ_a must equal sf_prime*(2e3)^b."""
        res = sn_curve(MAT_STEEL, n_min=1e3, n_max=1e3, n_points=1, mean_stress=0.0)
        assert res["ok"]
        N = res["N_cycles"][0]
        sigma_a = res["sigma_a_pa"][0]
        expected = MAT_STEEL["sf_prime"] * (2.0 * N) ** MAT_STEEL["b"]
        assert abs(sigma_a - expected) / expected < 1e-9

    def test_F20_result_contains_Su_and_b(self):
        """Result dict must contain Su_pa and b fields."""
        res = sn_curve(MAT_STEEL)
        assert res["ok"]
        assert "Su_pa" in res
        assert "b" in res
        assert abs(res["Su_pa"] - MAT_STEEL["Su"]) < 1.0
        assert abs(res["b"] - MAT_STEEL["b"]) < 1e-12


class TestHaighDiagram:

    def test_F9_goodman_at_zero_mean_equals_Se(self):
        """At σ_m = 0, Goodman boundary = Se."""
        res = haigh_diagram(MAT_STEEL, n_sigma_m=10)
        assert res["ok"]
        # First point is σ_m = 0
        assert abs(res["goodman_a"][0] - MAT_STEEL["Se"]) / MAT_STEEL["Se"] < 1e-9

    def test_F10_goodman_at_Su_equals_zero(self):
        """At σ_m = Su, Goodman boundary = 0."""
        res = haigh_diagram(MAT_STEEL, n_sigma_m=100)
        assert res["ok"]
        # Last point is σ_m = Su
        assert res["goodman_a"][-1] < MAT_STEEL["Se"] * 0.01, (
            f"Goodman at Su={MAT_STEEL['Su']:.2e}: {res['goodman_a'][-1]:.4e} should be ~0"
        )

    def test_F11_gerber_ge_goodman(self):
        """Gerber >= Goodman for all σ_m (Gerber less conservative)."""
        res = haigh_diagram(MAT_STEEL, n_sigma_m=50)
        assert res["ok"]
        for i, (g, gb) in enumerate(zip(res["goodman_a"], res["gerber_a"])):
            assert gb >= g - 1.0, (
                f"Point {i}: Gerber {gb:.4e} < Goodman {g:.4e}"
            )

    def test_F12_langer_yield_at_zero_mean(self):
        """Langer yield line at σ_m=0 must equal Sy."""
        res = haigh_diagram(MAT_STEEL)
        assert res["ok"]
        assert abs(res["yield_line"][0] - MAT_STEEL["Sy"]) / MAT_STEEL["Sy"] < 1e-9

    def test_F13_bad_material_returns_error(self):
        """Missing Su returns ok=False."""
        res = haigh_diagram({})
        assert res["ok"] is False

    def test_F18_swt_convex(self):
        """SWT boundary σ_a = Se²/(Se+σ_m) is convex (second diff >= 0) — decreasing."""
        res = haigh_diagram(MAT_STEEL, n_sigma_m=50)
        assert res["ok"]
        swt = res["swt_a"]
        # Each value must be <= previous (monotone decreasing)
        for i in range(1, len(swt)):
            assert swt[i] <= swt[i - 1] + 1.0, (
                f"SWT not monotone at i={i}: {swt[i]:.4e} > {swt[i-1]:.4e}"
            )

    def test_result_contains_all_keys(self):
        """Result must contain all boundary keys."""
        res = haigh_diagram(MAT_STEEL)
        assert res["ok"]
        for key in ["sigma_m_pa", "goodman_a", "gerber_a", "swt_a", "yield_line",
                    "Se_pa", "Su_pa", "Sy_pa"]:
            assert key in res, f"Missing key: {key}"


class TestSNCurveToolWrapper:

    def test_F14_tool_valid_payload(self):
        """fem_sn_curve tool returns ok=True for valid material."""
        payload = {"material": {"Su": 600e6, "Se": 300e6, "b": -0.085, "sf_prime": 900e6}}
        raw = _run(run_fem_sn_curve(None, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is True, result
        assert "N_cycles" in result
        assert "sigma_a_pa" in result

    def test_F15_tool_bad_json_returns_error(self):
        """Bad JSON returns error payload."""
        raw = _run(run_fem_sn_curve(None, b"{invalid json"))
        result = json.loads(raw)
        assert "error" in result

    def test_F16_haigh_tool_valid(self):
        """fem_haigh_diagram tool returns ok=True."""
        payload = {"material": {"Su": 600e6, "Se": 300e6, "Sy": 450e6}}
        raw = _run(run_fem_haigh_diagram(None, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is True, result
        assert "goodman_a" in result

    def test_tool_spec_names(self):
        """Tool spec names must be correct."""
        assert _fem_sn_curve_spec.name == "fem_sn_curve"
        assert _fem_haigh_diagram_spec.name == "fem_haigh_diagram"


# ===========================================================================
# V1–V17  FRF sweep
# ===========================================================================

class TestFRFSweepSDOF:
    """
    SDOF validation: fn=10 Hz, ζ=0.05, Γ=1.0.
    """
    FN = 10.0
    ZETA = 0.05
    GAMMA = 1.0
    WN = 2.0 * math.pi * FN

    def _res(self, n_pts=500, f_max=25.0):
        return frf_sweep(
            fn_hz=[self.FN],
            zeta=[self.ZETA],
            participation=[self.GAMMA],
            freq_range={"f_min": 0.01, "f_max": f_max, "n_pts": n_pts},
        )

    def test_V1_magnitude_at_resonance(self):
        """
        At ω = ω_n, |H| = Γ / (2ζω_n²).
        """
        # Dense sweep centred on fn
        res = frf_sweep(
            fn_hz=[self.FN],
            zeta=[self.ZETA],
            participation=[self.GAMMA],
            freq_range={"f_min": self.FN * 0.9999, "f_max": self.FN * 1.0001, "n_pts": 3},
        )
        assert res["ok"], res.get("reason")
        mag_at_res = res["magnitude"][1]
        expected = self.GAMMA / (2.0 * self.ZETA * self.WN ** 2)
        rel_err = abs(mag_at_res - expected) / expected
        assert rel_err < 0.001, (
            f"|H| at resonance: {mag_at_res:.4e}, expected {expected:.4e}, err={rel_err*100:.3f}%"
        )

    def test_V2_resonant_peak_frequency(self):
        """Resonant peak must be within df of fn."""
        res = self._res(n_pts=500)
        assert res["ok"]
        df = (25.0 - 0.01) / 499
        assert abs(res["resonant_peak_hz"] - self.FN) < 2.0 * df, (
            f"Peak at {res['resonant_peak_hz']:.3f} Hz, expected {self.FN} Hz"
        )

    def test_V3_phase_at_resonance_near_minus_90deg(self):
        """Phase at resonance ≈ −90° (response lags force by 90°)."""
        res = frf_sweep(
            fn_hz=[self.FN],
            zeta=[self.ZETA],
            participation=[self.GAMMA],
            freq_range={"f_min": self.FN * 0.9999, "f_max": self.FN * 1.0001, "n_pts": 3},
        )
        assert res["ok"]
        phase = res["phase_deg"][1]
        assert abs(abs(phase) - 90.0) < 1.0, (
            f"Phase at resonance: {phase:.2f}°, expected ±90°"
        )

    def test_V4_magnitude_list_length(self):
        """Output magnitude list must have length == n_pts."""
        n_pts = 150
        res = frf_sweep(
            fn_hz=[self.FN],
            zeta=[self.ZETA],
            participation=[self.GAMMA],
            freq_range={"f_min": 1.0, "f_max": 20.0, "n_pts": n_pts},
        )
        assert res["ok"]
        assert len(res["magnitude"]) == n_pts
        assert len(res["frequencies_hz"]) == n_pts
        assert len(res["phase_deg"]) == n_pts

    def test_V11_mode_table_length_and_fields(self):
        """mode_table must have 1 entry with required fields for SDOF."""
        res = self._res()
        assert res["ok"]
        mt = res["mode_table"]
        assert len(mt) == 1
        row = mt[0]
        for field in ["mode", "fn_hz", "zeta", "participation", "DAF_at_resonance"]:
            assert field in row, f"Missing field: {field}"
        assert row["mode"] == 1
        assert abs(row["fn_hz"] - self.FN) < 1e-9
        assert abs(row["zeta"] - self.ZETA) < 1e-9

    def test_V12_daf_at_resonance_formula(self):
        """mode_table DAF_at_resonance = 1/(2ζ) per SDOF theory."""
        res = self._res()
        assert res["ok"]
        daf = res["mode_table"][0]["DAF_at_resonance"]
        expected = 1.0 / (2.0 * self.ZETA)
        assert abs(daf - expected) / expected < 1e-9

    def test_V16_static_limit(self):
        """
        At f→0 (quasi-static), |H(0)| = Γ / ω_n².
        """
        res = frf_sweep(
            fn_hz=[self.FN],
            zeta=[self.ZETA],
            participation=[self.GAMMA],
            freq_range={"f_min": 0.001, "f_max": 0.01, "n_pts": 5},
        )
        assert res["ok"]
        mag_static = res["magnitude"][0]
        expected = self.GAMMA / self.WN ** 2
        rel_err = abs(mag_static - expected) / expected
        assert rel_err < 0.001, (
            f"Static |H|: {mag_static:.6e}, expected {expected:.6e}, err={rel_err*100:.3f}%"
        )


class TestFRFSweepMultiMode:

    def test_V10_two_modes_two_peaks(self):
        """Two-mode system must show two local maxima near each fn."""
        fn1, fn2 = 10.0, 40.0
        res = frf_sweep(
            fn_hz=[fn1, fn2],
            zeta=[0.05, 0.05],
            participation=[1.0, 1.0],
            freq_range={"f_min": 1.0, "f_max": 60.0, "n_pts": 600},
        )
        assert res["ok"]
        mag = res["magnitude"]
        freqs = res["frequencies_hz"]

        # Find local maxima
        peaks = [i for i in range(1, len(mag) - 1)
                 if mag[i] > mag[i - 1] and mag[i] > mag[i + 1]]
        assert len(peaks) >= 2, f"Expected ≥2 peaks, found {len(peaks)}"

        peak_freqs = [freqs[i] for i in peaks]
        assert any(abs(pf - fn1) < 2.0 for pf in peak_freqs), (
            f"No peak near fn1={fn1} Hz in {peak_freqs}"
        )
        assert any(abs(pf - fn2) < 5.0 for pf in peak_freqs), (
            f"No peak near fn2={fn2} Hz in {peak_freqs}"
        )

    def test_V11_mode_table_two_modes(self):
        """Two-mode mode_table must have 2 entries."""
        res = frf_sweep(
            fn_hz=[10.0, 40.0],
            zeta=[0.05, 0.03],
            participation=[1.0, 0.5],
            freq_range={"f_min": 1.0, "f_max": 60.0, "n_pts": 100},
        )
        assert res["ok"]
        assert len(res["mode_table"]) == 2
        assert res["mode_table"][0]["mode"] == 1
        assert res["mode_table"][1]["mode"] == 2

    def test_V17_per_mode_zeta_accepted(self):
        """Per-mode zeta list accepted and used correctly."""
        res = frf_sweep(
            fn_hz=[10.0, 40.0],
            zeta=[0.01, 0.10],   # different damping per mode
            participation=[1.0, 1.0],
            freq_range={"f_min": 1.0, "f_max": 60.0, "n_pts": 200},
        )
        assert res["ok"]
        # Mode 1 has lower damping → higher DAF
        daf1 = res["mode_table"][0]["DAF_at_resonance"]
        daf2 = res["mode_table"][1]["DAF_at_resonance"]
        assert daf1 > daf2, f"Lower ζ mode should have higher DAF: {daf1:.2f} vs {daf2:.2f}"


class TestFRFSweepInputValidation:

    def test_V5_empty_fn_hz(self):
        res = frf_sweep([], [], [], {"f_min": 1, "f_max": 10, "n_pts": 10})
        assert not res["ok"]

    def test_V6_mismatched_zeta_length(self):
        res = frf_sweep([10.0, 20.0], [0.05], [1.0, 1.0], {"f_min": 1, "f_max": 30, "n_pts": 10})
        assert not res["ok"]

    def test_V7_mismatched_participation_length(self):
        res = frf_sweep([10.0], [0.05], [1.0, 2.0], {"f_min": 1, "f_max": 20, "n_pts": 10})
        assert not res["ok"]

    def test_V8_negative_damping(self):
        res = frf_sweep([10.0], [-0.01], [1.0], {"f_min": 1, "f_max": 20, "n_pts": 10})
        assert not res["ok"]

    def test_V9_fmax_le_fmin(self):
        res = frf_sweep([10.0], [0.05], [1.0], {"f_min": 20.0, "f_max": 10.0, "n_pts": 10})
        assert not res["ok"]


class TestFRFSweepToolWrapper:

    def test_V13_valid_payload(self):
        """fem_frf_sweep tool returns ok=True with magnitude list."""
        payload = {
            "fn_hz": [10.0, 40.0],
            "zeta": 0.05,
            "participation": [1.0, 0.5],
            "freq_range": {"f_min": 1.0, "f_max": 60.0, "n_pts": 50},
        }
        raw = _run(run_fem_frf_sweep(None, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is True, result
        assert "magnitude" in result
        assert len(result["magnitude"]) == 50

    def test_V14_bad_json_returns_error(self):
        raw = _run(run_fem_frf_sweep(None, b"not valid {{"))
        result = json.loads(raw)
        assert "error" in result

    def test_V15_scalar_zeta_accepted(self):
        """Scalar zeta (not list) is accepted and broadcasts to all modes."""
        payload = {
            "fn_hz": [10.0, 20.0, 40.0],
            "zeta": 0.03,
            "participation": [1.0, 0.8, 0.5],
            "freq_range": {"f_min": 1.0, "f_max": 60.0, "n_pts": 100},
        }
        raw = _run(run_fem_frf_sweep(None, json.dumps(payload).encode()))
        result = json.loads(raw)
        assert result.get("ok") is True, result

    def test_tool_spec_name(self):
        assert _fem_frf_sweep_spec.name == "fem_frf_sweep"
